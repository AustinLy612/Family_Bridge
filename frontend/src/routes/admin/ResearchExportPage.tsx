/**
 * Admin: research export (Plan §5.10, §8.5; D80-D82). Shows what the zip contains (files and
 * row counts, never values) and downloads it. The server audits every download. Pseudonymous,
 * no free text; adolescent and caregiver files are separate; consent windows apply.
 */
import { useQuery } from "@tanstack/react-query";
import { FileDown } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { research, type ExportFile } from "../../api/research";
import { ErrorNotice, Notice } from "../../components/Forms";
import { PrimaryButton } from "../../design";
import { Page } from "../Page";
import "./admin.css";

const SCOPES = ["shared", "adolescent", "caregiver"] as const;

export function ResearchExportPage() {
  const { t } = useTranslation();
  const [includeDemo, setIncludeDemo] = useState(false);
  const q = useQuery({
    queryKey: ["research-export", includeDemo],
    queryFn: () => research.preview(includeDemo),
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);

  async function download() {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const { blob, filename } = await research.download(includeDemo);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const files = q.data?.files ?? [];
  return (
    <Page title={t("nav.export")} subtitle={t("admin.export.subtitle")} icon={<FileDown size={22} />}>
      <div className="fb-stack">
        <section className="fb-card fb-stack" aria-labelledby="export-rules">
          <h2 id="export-rules" className="fb-card__title">
            {t("admin.export.rulesTitle")}
          </h2>
          <ul className="fb-export-rules">
            {(["pseudonymous", "separate", "consent", "dates", "dictionary", "audited"] as const).map((k) => (
              <li key={k}>{t(`admin.export.rules.${k}`)}</li>
            ))}
          </ul>
          <label className="fb-check">
            <input type="checkbox" checked={includeDemo} onChange={(e) => setIncludeDemo(e.target.checked)} />{" "}
            {t("admin.export.includeDemo")}
          </label>
          <ErrorNotice error={error ?? q.error} />
          {done && <Notice>{t("admin.export.done")}</Notice>}
          <div>
            <PrimaryButton onClick={() => void download()} disabled={busy || !q.data}>
              {busy ? t("admin.export.preparing") : t("admin.export.download")}
            </PrimaryButton>
          </div>
        </section>
        {SCOPES.map((scope) => (
          <FileTable key={scope} scope={scope} files={files.filter((f) => f.scope === scope)} />
        ))}
      </div>
    </Page>
  );
}

function FileTable({ scope, files }: { scope: string; files: ExportFile[] }) {
  const { t } = useTranslation();
  if (files.length === 0) return null;
  const id = `export-${scope}`;
  return (
    <section className="fb-card" aria-labelledby={id}>
      <h2 id={id} className="fb-card__title">
        {t(`admin.export.scope.${scope}`)}
      </h2>
      <table className="fb-table" aria-labelledby={id} data-testid={`export-${scope}`}>
        <thead>
          <tr>
            <th scope="col">{t("admin.export.file")}</th>
            <th scope="col">{t("admin.export.rows")}</th>
          </tr>
        </thead>
        <tbody>
          {files.map((f) => (
            <tr key={f.path}>
              <td>
                <code>{f.path}</code>
              </td>
              <td>{f.rows}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
