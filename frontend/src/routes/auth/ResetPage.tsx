/** Set a new password with a staff-issued reset code (D30). Signs the account out everywhere. */
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { post } from "../../api/client";
import type { CodeInfo } from "../../api/types";
import { ErrorNotice, Notice, TextField } from "../../components/Forms";
import { PrimaryButton } from "../../design";
import { PublicFrame } from "./PublicFrame";
import { CodeStep } from "./RedeemPage";

export function ResetPage() {
  const { t } = useTranslation();
  const [code, setCode] = useState<string | null>(null);
  const [info, setInfo] = useState<CodeInfo | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const mismatch = confirm.length > 0 && confirm !== password;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!code || mismatch) return;
    setBusy(true);
    setError(null);
    try {
      await post("/auth/reset", { code, password });
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicFrame>
      <section className="fb-card" aria-labelledby="reset-title">
        <h1 id="reset-title" className="fb-card__title">
          {t("auth.resetTitle")}
        </h1>
        {done ? (
          <>
            <Notice>{t("auth.resetDone")}</Notice>
            <Link to="/" className="fb-btn fb-btn--primary">
              {t("auth.signIn")}
            </Link>
          </>
        ) : !code || !info ? (
          <>
            <p>{t("auth.resetIntro")}</p>
            <CodeStep
              purpose="reset"
              onValid={(c, i) => {
                setCode(c);
                setInfo(i);
              }}
            />
          </>
        ) : (
          <form onSubmit={onSubmit} className="fb-form" noValidate>
            <Notice>{t("auth.resetFor", { username: info.username ?? "" })}</Notice>
            <TextField
              label={t("auth.newPassword")}
              hint={t("auth.passwordHint")}
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <TextField
              label={t("auth.confirmPassword")}
              type="password"
              autoComplete="new-password"
              value={confirm}
              error={mismatch ? t("auth.passwordMismatch") : undefined}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
            <ErrorNotice error={error} />
            <PrimaryButton type="submit" disabled={busy || !password || !confirm || mismatch}>
              {t("auth.setPassword")}
            </PrimaryButton>
          </form>
        )}
      </section>
    </PublicFrame>
  );
}
