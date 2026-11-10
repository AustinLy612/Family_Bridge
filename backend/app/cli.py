"""Management commands: `python -m app.cli <command>` (Plan §3.1 "CLI management commands")."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any

from alembic import command
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.content.loader import ContentError, load_content
from app.core import audit
from app.core.db import alembic_config, get_engine
from app.core.security import (
    hash_password,
    new_pseudonym,
    normalise_username,
    password_problems,
    username_valid,
)
from app.core.sessions import utcnow
from app.models import Role, User, UserStatus
from app.services.seed import SeedExistsError, seed_demo, write_output
from app.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def _check_content(_: argparse.Namespace) -> int:
    try:
        bundle = load_content(get_settings().content_dir)
    except ContentError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"content OK: {len(bundle.files)} file(s), version {bundle.aggregate_hash}")
    return 0


def _migrate(_: argparse.Namespace) -> int:
    from app.core.db import ensure_app_role

    settings = get_settings()
    owner_url = settings.migration_database_url or settings.database_url
    command.upgrade(alembic_config(owner_url), "head")
    password = settings.app_db_password.get_secret_value()
    if password:
        ensure_app_role(owner_url, settings.app_db_user, password)
        print(f"app role {settings.app_db_user} ready (DML only; audit log append-only)")
    return 0


def _create_admin(args: argparse.Namespace) -> int:
    username = normalise_username(args.username)
    if not username_valid(username):
        print("username must be 3-32 chars of a-z 0-9 . _ -", file=sys.stderr)
        return 2
    password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass()
    problems = password_problems(password, username=username)
    if problems:
        print("password rejected: " + ", ".join(problems), file=sys.stderr)
        return 2
    with Session(get_engine()) as db, db.begin():
        if db.execute(select(User.id).where(func.lower(User.username) == username)).first():
            print("username already exists", file=sys.stderr)
            return 1
        user = User(
            pseudonym_code=new_pseudonym(),
            username=username,
            role=Role.admin,
            display_alias=args.alias,
            language=args.language,
            a11y_prefs={},
            password_hash=hash_password(password),
            status=UserStatus.active,
            is_demo=False,
            failed_logins=0,
            onboarded_at=utcnow(),
        )
        db.add(user)
        db.flush()
        audit.record(
            db, "user.created_admin_cli", actor=None, target_type="user", target_id=user.id
        )
    print(f"admin created: {username}")
    return 0


def _seed_demo(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.is_production:
        print("refusing to seed demo data in production", file=sys.stderr)
        return 2
    try:
        with Session(get_engine()) as db, db.begin():
            result = seed_demo(db)
    except SeedExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = write_output(result, Path(args.out))
    print(f"demo data created: {len(result.accounts)} accounts; credentials written to {path}")
    return 0


def _seed_demo_activity(_: argparse.Namespace) -> int:
    """Add Phase 7-8 demo activity to an older demo database (idempotent)."""
    from app.services.seed_activity import seed_activity

    if get_settings().is_production:
        print("refusing to seed demo data in production", file=sys.stderr)
        return 2
    try:
        with Session(get_engine()) as db, db.begin():
            added = seed_activity(db)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("demo activity added" if added else "demo activity already present")
    return 0


def _verify_audit(_: argparse.Namespace) -> int:
    with Session(get_engine()) as db:
        report = audit.verify_chain(db)
    if report.ok:
        print(f"audit chain OK: {report.entries} entries")
        return 0
    print(f"audit chain BROKEN at id {report.first_bad_id}: {report.reason}", file=sys.stderr)
    return 1


# --- research export (Plan §5.10; Phase 9) ------------------------------------------------

DICTIONARY_DOC = REPO_ROOT / "docs" / "research" / "DATA_DICTIONARY.md"


def _export_research(args: argparse.Namespace) -> int:
    """Write the pseudonymous research export zip (audited, like the admin download)."""
    from datetime import date

    from app.research import export as rx

    settings = get_settings()
    bundle = load_content(settings.content_dir)
    out = (
        Path(args.out)
        if args.out
        else REPO_ROOT / "exports" / f"familybridge-research-{date.today().isoformat()}.zip"
    )
    with Session(get_engine()) as db, db.begin():
        result = rx.build(
            db, bundle, settings.secret_key.get_secret_value(), include_demo=args.include_demo
        )
        data = rx.to_zip(result)
        audit.record(
            db,
            "research.export",
            details={
                "via": "cli",
                "include_demo": args.include_demo,
                "rows": result.counts,
                "bytes": len(data),
            },
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"wrote {out} ({len(data)} bytes)")
    for path, n in result.counts.items():
        print(f"  {path}: {n}")
    return 0


def _research_dictionary(args: argparse.Namespace) -> int:
    """Regenerate docs/research/DATA_DICTIONARY.md from the export spec."""
    from app.research.dictionary import render

    settings = get_settings()
    text = render(load_content(settings.content_dir))
    if args.check:
        if not DICTIONARY_DOC.exists() or DICTIONARY_DOC.read_text(encoding="utf-8") != text:
            print("DATA_DICTIONARY.md is out of date: run `research-dictionary`", file=sys.stderr)
            return 1
        print("data dictionary up to date")
        return 0
    DICTIONARY_DOC.parent.mkdir(parents=True, exist_ok=True)
    DICTIONARY_DOC.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {DICTIONARY_DOC}")
    return 0


# --- knowledge base (Plan §5.3; Phase 3) -------------------------------------------------


def _manual_path(arg: str | None) -> Path | None:
    if arg:
        return Path(arg)
    src = get_settings().knowledge_source_dir
    found = sorted(src.glob("*DBT*手册*.pdf")) + sorted(src.glob("*DBTA*.pdf"))
    return found[0] if found else None


def _kb_ingest(args: argparse.Namespace) -> int:
    from app.kb import ingest as kbi
    from app.kb.embedder import get_embedder

    settings = get_settings()
    bundle = load_content(settings.content_dir)
    index = bundle.handouts
    pdf = _manual_path(args.pdf)
    if index is None or pdf is None or not pdf.is_file():
        print("need content/skills/handouts.yaml and the manual PDF (--pdf)", file=sys.stderr)
        return 2
    try:
        transcriptions = kbi.load_transcriptions(
            settings.knowledge_work_dir / "transcriptions", index
        )
        pages = kbi.read_pdf(pdf)
        embedder = get_embedder(settings)
        print(f"embedding with {embedder.name} (the first run loads the model) ...")
        with Session(get_engine()) as db, db.begin():
            doc = kbi.ingest(
                db,
                raw_pages=pages,
                source_name=pdf.name,
                source_sha256=kbi.sha256_file(pdf),
                index=index,
                taxonomy=bundle.taxonomy,
                transcriptions=transcriptions,
                embedder=embedder,
                progress=lambda done, total: print(f"  {done}/{total} chunks", end="\r"),
            )
            print()
            print(f"knowledge base v{doc.version} active: {doc.chunk_count} chunks")
            print(json.dumps(doc.stats, ensure_ascii=False, indent=1))
    except kbi.IngestError as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _kb_status(_: argparse.Namespace) -> int:
    from app.models.knowledge import KnowledgeDocument

    with Session(get_engine()) as db:
        docs = db.execute(
            select(KnowledgeDocument).order_by(KnowledgeDocument.version.desc())
        ).scalars()
        rows = [
            f"v{d.version} {d.status.value:<10} {d.chunk_count:>4} chunks  {d.embedding_model}  "
            f"{d.created_at:%Y-%m-%d %H:%M}"
            for d in docs
        ]
    print("\n".join(rows) if rows else "knowledge base is empty: run `kb ingest`")
    return 0


def _kb_service() -> Any:
    from app.kb.retrieval import KnowledgeService

    settings = get_settings()
    service = KnowledgeService(settings)
    service.prepare_tokenizer(load_content(settings.content_dir).taxonomy)
    return service


def _kb_search(args: argparse.Namespace) -> int:
    service = _kb_service()
    with Session(get_engine()) as db, db.begin():
        res = service.search(
            db,
            args.query,
            language=args.language,
            caller="cli",
            skill_ids=args.skill or [],
            module=args.module,
            k=args.k,
        )
    print(f"v{res.document_version}  sufficient={res.sufficient}  {res.latency_ms} ms")
    for i, h in enumerate(res.hits, 1):
        pages = ",".join(map(str, h.pdf_pages))
        print(
            f"{i}. {h.handout_id:<8} p{pages:<8} sim={h.similarity:.3f} rrf={h.score:.4f} "
            f"sem={h.semantic_rank} kw={h.keyword_rank}  {h.handout_title_zh}"
        )
        if args.show_text:  # local console only; manual text never leaves the machine (D7)
            print("   " + h.text[:120].replace("\n", " / "))
    return 0


def _kb_eval(args: argparse.Namespace) -> int:
    from app.kb.evaluation import run_eval
    from app.kb.ingest import active_document

    bundle = load_content(get_settings().content_dir)
    eval_set, index = bundle.retrieval_eval, bundle.handouts
    if eval_set is None or index is None:
        print("no eval set (content/eval/retrieval/) or handout index", file=sys.stderr)
        return 2
    service = _kb_service()
    module_of = {h.id: h.module for h in index.handouts}
    with Session(get_engine()) as db, db.begin():
        report = run_eval(db, service, eval_set, module_of)
        out = report.as_dict()
        hits, misses = sorted(report.similarities_hit), sorted(report.similarities_miss)
        out["top_similarity"] = {
            "hits_min": round(hits[0], 4) if hits else None,
            "hits_median": round(hits[len(hits) // 2], 4) if hits else None,
            "misses_max": round(misses[-1], 4) if misses else None,
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))
        if args.record:
            doc = active_document(db)
            if doc is not None:
                doc.stats = {**doc.stats, "eval": {**out, "eval_set_version": eval_set.version}}
                audit.record(
                    db,
                    "kb.eval_recorded",
                    target_type="knowledge_document",
                    target_id=doc.id,
                    details={"passed": report.passed, "recall": out["overall"]["recall"]},
                )
    return 0 if report.passed else 1


def _kb_fingerprint(args: argparse.Namespace) -> int:
    from app.kb import fingerprint as fp
    from app.kb import ingest as kbi
    from app.kb import text as kbtext

    settings = get_settings()
    index = load_content(settings.content_dir).handouts
    pdf = _manual_path(args.pdf)
    if index is None or pdf is None or not pdf.is_file():
        print("need content/skills/handouts.yaml and the manual PDF (--pdf)", file=sys.stderr)
        return 2
    pages = kbi.read_pdf(pdf)
    frequent = kbtext.frequent_lines(pages)
    texts = ["\n".join(kbtext.clean_page(p, frequent)) for p in pages]
    tdir = settings.knowledge_work_dir / "transcriptions"
    texts += ["\n".join(t.lines) for t in kbi.load_transcriptions(tdir, index).values()]
    hashes = fp.build(texts)
    fp.write(hashes)
    print(f"wrote {len(hashes)} window hashes to {fp.FINGERPRINT_PATH}")
    return 0


def _kb_overlap_check(_: argparse.Namespace) -> int:
    from app.kb import fingerprint as fp

    found = fp.scan_repo(REPO_ROOT)
    for rel, o in found:
        print(f"{rel}: {o.length} characters match the manual (starts '{o.excerpt}')")
    print(f"overlap check: {len(found)} problem(s)")
    return 1 if found else 0


# --- AI layer (Plan §5.4, §7.3; Phase 4) ------------------------------------------------


def _ai_stack() -> tuple[Any, Any, Any]:
    """(content, AIService, SafetyService) wired exactly like the API, with the real KB."""
    from app.ai.wiring import LLMRiskAssessor, build_ai_service
    from app.safety.service import SafetyService

    settings = get_settings()
    content = load_content(settings.content_dir)

    def session_factory() -> Session:
        return Session(get_engine(), expire_on_commit=False)

    ai = build_ai_service(
        content, settings, knowledge=_kb_service(), session_factory=session_factory
    )
    return content, ai, SafetyService(content, settings, LLMRiskAssessor(ai))


def _ai_status(_: argparse.Namespace) -> int:
    from app.models.ai import AIEvalRun

    _, ai, _ = _ai_stack()
    print(
        f"provider {ai.provider.name}  model {ai.provider.model}  "
        f"breaker {ai.provider.breaker.state}"
    )
    with Session(get_engine()) as db:
        runs = db.execute(
            select(AIEvalRun).order_by(AIEvalRun.created_at.desc()).limit(10)
        ).scalars()
        for r in runs:
            print(f"{r.created_at:%Y-%m-%d %H:%M} {r.kind:<12} {r.model:<16} passed={r.passed}")
    return 0


def _ai_smoke(_: argparse.Namespace) -> int:
    """One real call per language (personal_inquiry); prints outcome only, never the text."""
    _, ai, _ = _ai_stack()
    ok = True
    for lang in ("zh-CN", "en"):
        r = ai.run(
            None,
            "personal_inquiry",
            {"mood": 3, "mood_note": ""},
            role="adolescent",
            language=lang,
            caller="cli:smoke",
            use_cache=False,
        )
        print(f"{lang}: outcome={r.outcome.value} source={r.source.value} failures={r.failures}")
        ok = ok and r.output is not None and r.outcome.value != "fallback"
    return 0 if ok else 1


def _ai_eval(args: argparse.Namespace) -> int:
    from app.ai import evaluation as ev

    content, ai, safety = _ai_stack()
    sets = content.adversarial_sets
    if args.category:
        sets = [s for s in sets if s.category in args.category]
    with Session(get_engine(), expire_on_commit=False) as db:
        report = ev.run_adversarial(db, ai, safety, sets)
        summary = report.summary()
        ev.record(db, "adversarial", ai, report.passed, summary)
        db.commit()
    brief = {k: v for k, v in summary.items() if k != "cases"}
    brief["failed_cases"] = [
        {
            "id": c["id"],
            "severity": c["severity"],
            "observed": c["observed"],
            "detail": c["detail"],
            "evidence": c["evidence"],
        }
        for c in summary["cases"]
        if not c["passed"]
    ]
    print(json.dumps(brief, ensure_ascii=False, indent=1))
    return 0 if report.passed else 1


def _ai_sweep(args: argparse.Namespace) -> int:
    from app.ai import evaluation as ev

    content, ai, _ = _ai_stack()
    skills = (
        content.taxonomy.skill_ids() if args.all and content.taxonomy else list(ev.SAMPLE_SKILLS)
    )
    with Session(get_engine(), expire_on_commit=False) as db:
        report = ev.run_sweep(db, ai, skills)
        summary = report.summary()
        ev.record(db, "sweep_all" if args.all else "sweep_sample", ai, report.passed, summary)
        db.commit()
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.export:
        n = ev.export_for_review(report, content.golden_eval, Path(args.export))
        print(f"exported {n} outputs for clinician review to {args.export}")
    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-content", help="validate every file under content/")
    sub.add_parser("migrate", help="apply database migrations up to head")
    ca = sub.add_parser("create-admin", help="create an admin account (password via prompt)")
    ca.add_argument("--username", required=True)
    ca.add_argument("--alias", default="Admin")
    ca.add_argument("--language", choices=["zh-CN", "en"], default="zh-CN")
    ca.add_argument("--password-stdin", action="store_true", help="read password from stdin")
    sd = sub.add_parser("seed-demo", help="create fictional demo accounts (not in production)")
    sd.add_argument("--out", default=str(REPO_ROOT / "seed_output"))
    sub.add_parser(
        "seed-demo-activity", help="add Phase 7-8 demo activity to an existing demo seed"
    )
    sub.add_parser("verify-audit", help="verify the audit log hash chain")
    ex = sub.add_parser("export-research", help="write the pseudonymous research export zip")
    ex.add_argument("--out", help="zip path (default: exports/familybridge-research-DATE.zip)")
    ex.add_argument("--include-demo", action="store_true", help="include demo groups/accounts")
    rd = sub.add_parser("research-dictionary", help="regenerate docs/research/DATA_DICTIONARY.md")
    rd.add_argument("--check", action="store_true", help="fail if the file is out of date")
    kb = sub.add_parser("kb", help="knowledge base: ingest, status, search, eval, fingerprint")
    kbs = kb.add_subparsers(dest="kb_cmd", required=True)
    ki = kbs.add_parser("ingest", help="ingest the manual PDF into a new active version")
    ki.add_argument("--pdf", help="path to the manual (default: KNOWLEDGE_SOURCE_DIR)")
    kbs.add_parser("status", help="list knowledge-base versions")
    ks = kbs.add_parser("search", help="hybrid search (logged as caller=cli)")
    ks.add_argument("query")
    ks.add_argument("--language", choices=["zh-CN", "en"], default="zh-CN")
    ks.add_argument("--skill", action="append")
    ks.add_argument("--module")
    ks.add_argument("-k", type=int, default=5)
    ks.add_argument("--show-text", action="store_true", help="print chunk openings (local only)")
    ke = kbs.add_parser("eval", help="recall@k / MRR on content/eval/retrieval")
    ke.add_argument("--record", action="store_true", help="store metrics on the active version")
    kf = kbs.add_parser("fingerprint", help="regenerate scripts/manual_fingerprint.txt")
    kf.add_argument("--pdf")
    kbs.add_parser("overlap-check", help="fail if repository text copies the manual")
    ai = sub.add_parser("ai", help="AI layer: status, smoke, eval (adversarial), sweep")
    ais = ai.add_subparsers(dest="ai_cmd", required=True)
    ais.add_parser("status", help="provider, breaker and recent evaluation runs")
    ais.add_parser("smoke", help="one real call per language; prints outcomes only")
    ae = ais.add_parser("eval", help="run the adversarial benchmark (content/eval/adversarial)")
    ae.add_argument("--category", action="append")
    asw = ais.add_parser("sweep", help="every function x role x language on sample skills")
    asw.add_argument("--all", action="store_true", help="all 40 skills instead of the sample")
    asw.add_argument("--export", help="write outputs + golden key points as JSONL (git-ignored)")
    args = parser.parse_args(argv)
    handlers = {
        "check-content": _check_content,
        "migrate": _migrate,
        "create-admin": _create_admin,
        "seed-demo": _seed_demo,
        "seed-demo-activity": _seed_demo_activity,
        "verify-audit": _verify_audit,
        "export-research": _export_research,
        "research-dictionary": _research_dictionary,
    }
    kb_handlers = {
        "ingest": _kb_ingest,
        "status": _kb_status,
        "search": _kb_search,
        "eval": _kb_eval,
        "fingerprint": _kb_fingerprint,
        "overlap-check": _kb_overlap_check,
    }
    ai_handlers = {"status": _ai_status, "smoke": _ai_smoke, "eval": _ai_eval, "sweep": _ai_sweep}
    if args.cmd == "ai":
        return ai_handlers[args.ai_cmd](args)
    if args.cmd == "kb":
        return kb_handlers[args.kb_cmd](args)
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
