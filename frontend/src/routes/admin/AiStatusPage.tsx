/**
 * Admin: AI layer status (Plan §5.4, §7.3; Phase 4). Read-only.
 * Provider, circuit breaker, per-function usage and fallbacks, rejection codes, prompt approval
 * and evaluation runs. Counts and codes only: no participant text and no AI output (privacy).
 * Evaluations (`ai eval`, `ai sweep`) run from the CLI.
 */
import { useQuery } from "@tanstack/react-query";
import { Activity, LifeBuoy, Sparkles, Archive } from "lucide-react";
import { useTranslation } from "react-i18next";
import { get } from "../../api/client";
import type { AiEvalRun, AiStatus } from "../../api/types";
import { ErrorNotice, Notice } from "../../components/Forms";
import { Chip, StatTile } from "../../design";
import { Page } from "../Page";
import { useDateTime } from "../safety/time";

function pct(x: number) {
  return `${Math.round(x * 1000) / 10}%`;
}

function num(v: unknown): number {
  return typeof v === "number" ? v : 0;
}

function EvalLine({ run }: { run: AiEvalRun }) {
  const { t } = useTranslation();
  const when = useDateTime();
  const h = run.headline;
  const sev = (h.by_severity as Record<string, { cases: number; passed: number }> | undefined)?.high;
  return (
    <li>
      <Chip tone={run.passed ? "blue" : "amber"}>
        {t(run.passed ? "aiAdmin.evalPassed" : "aiAdmin.evalFailed")}
      </Chip>{" "}
      {t("aiAdmin.evalItem", {
        kind: t(`aiAdmin.evalKind.${run.kind}`, { defaultValue: run.kind }),
        model: run.model,
        when: when(run.created_at),
      })}
      {sev && <div className="fb-setting__hint">{t("aiAdmin.evalHigh", sev)}</div>}
      {typeof h.calls === "number" && (
        <div className="fb-setting__hint">
          {t("aiAdmin.evalCalls", { calls: h.calls, rate: pct(num(h.fallback_rate)) })}
        </div>
      )}
    </li>
  );
}

export function AiStatusPage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["admin", "ai"], queryFn: () => get<AiStatus>("/admin/ai") });
  const d = q.data;
  const approvals = d
    ? d.prompts.reduce<Record<string, number>>((acc, p) => {
        acc[p.approval] = (acc[p.approval] ?? 0) + 1;
        return acc;
      }, {})
    : {};
  const codes = d ? Object.entries(d.failure_codes).sort((a, b) => b[1] - a[1]) : [];
  return (
    <Page title={t("nav.aiLayer")} subtitle={t("aiAdmin.subtitle")} icon={<Sparkles size={22} />}>
      <div className="fb-stack">
        <Notice>{t("aiAdmin.notice")}</Notice>
        <ErrorNotice error={q.error} />
        {d && (
          <>
            <div className="fb-stats">
              <StatTile
                icon={<Activity size={20} />}
                value={d.calls}
                caption={t("aiAdmin.calls", { days: d.days })}
              />
              <StatTile icon={<LifeBuoy size={20} />} value={d.fallbacks} caption={t("aiAdmin.fallbacks")} />
              <StatTile
                icon={<Archive size={20} />}
                value={d.cache_items}
                caption={t("aiAdmin.cacheItems")}
              />
            </div>

            <section className="fb-card" aria-labelledby="ai-provider">
              <h2 id="ai-provider" className="fb-card__title">
                {t("aiAdmin.provider")}
              </h2>
              <dl className="fb-dl">
                <dt>{t("aiAdmin.provider")}</dt>
                <dd>{d.provider}</dd>
                <dt>{t("aiAdmin.model")}</dt>
                <dd>{d.model}</dd>
                <dt>{t("aiAdmin.breaker")}</dt>
                <dd>
                  <Chip tone={d.breaker === "closed" ? "blue" : "amber"}>
                    {t(`aiAdmin.breakerState.${d.breaker}`)}
                  </Chip>
                </dd>
                <dt>{t("aiAdmin.fallbackRate")}</dt>
                <dd>{d.calls ? pct(d.fallbacks / d.calls) : "—"}</dd>
              </dl>
            </section>

            <section className="fb-card" aria-labelledby="ai-functions">
              <h2 id="ai-functions" className="fb-card__title">
                {t("aiAdmin.functionsTitle")}
              </h2>
              {d.functions.length === 0 ? (
                <p>{t("aiAdmin.noCalls")}</p>
              ) : (
                <table className="fb-table" aria-labelledby="ai-functions">
                  <thead>
                    <tr>
                      <th scope="col">{t("aiAdmin.function")}</th>
                      <th scope="col">{t("aiAdmin.callsCol")}</th>
                      <th scope="col">{t("aiAdmin.fallbacksCol")}</th>
                      <th scope="col">{t("aiAdmin.repairedCol")}</th>
                      <th scope="col">{t("aiAdmin.retriedCol")}</th>
                      <th scope="col">{t("aiAdmin.generalCol")}</th>
                      <th scope="col">{t("aiAdmin.latencyCol")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.functions.map((f) => (
                      <tr key={f.function}>
                        <td>
                          <code>{f.function}</code>
                        </td>
                        <td>{f.calls}</td>
                        <td>{f.fallbacks}</td>
                        <td>{f.repaired}</td>
                        <td>{f.retried}</td>
                        <td>{f.general}</td>
                        <td>
                          {f.median_latency_ms === null
                            ? "—"
                            : t("aiAdmin.ms", { value: f.median_latency_ms })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section className="fb-card" aria-labelledby="ai-failures">
              <h2 id="ai-failures" className="fb-card__title">
                {t("aiAdmin.failuresTitle")}
              </h2>
              {codes.length === 0 ? (
                <p>{t("aiAdmin.noFailures")}</p>
              ) : (
                <table className="fb-table" aria-labelledby="ai-failures">
                  <thead>
                    <tr>
                      <th scope="col">{t("aiAdmin.failureCode")}</th>
                      <th scope="col">{t("aiAdmin.count")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {codes.map(([code, n]) => (
                      <tr key={code}>
                        <td>
                          <code>{code}</code>
                        </td>
                        <td>{n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section className="fb-card" aria-labelledby="ai-evals">
              <h2 id="ai-evals" className="fb-card__title">
                {t("aiAdmin.evalTitle")}
              </h2>
              {d.eval_runs.length === 0 ? (
                <p>{t("aiAdmin.noEval")}</p>
              ) : (
                <ul className="fb-timeline">
                  {d.eval_runs.map((r) => (
                    <EvalLine key={`${r.kind}-${r.created_at}`} run={r} />
                  ))}
                </ul>
              )}
            </section>

            <section className="fb-card" aria-labelledby="ai-prompts">
              <h2 id="ai-prompts" className="fb-card__title">
                {t("aiAdmin.promptsTitle")}
              </h2>
              <p>{t("aiAdmin.promptsHint", { count: d.prompts.length, fallbacks: d.fallback_files })}</p>
              <p>
                {Object.entries(approvals).map(([status, n]) => (
                  <Chip key={status} tone="outline">
                    {t("aiAdmin.promptCount", {
                      status: t(`aiAdmin.approval.${status}`, { defaultValue: status }),
                      count: n,
                    })}
                  </Chip>
                ))}{" "}
                {Object.entries(d.cache_by_review).map(([status, n]) => (
                  <Chip key={status} tone="outline">
                    {t("aiAdmin.promptCount", { status: t(`aiAdmin.cacheReview.${status}`), count: n })}
                  </Chip>
                ))}
              </p>
            </section>
          </>
        )}
      </div>
    </Page>
  );
}
