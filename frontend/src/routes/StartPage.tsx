/** Start page: sign in, or redeem an invitation / reset code (Plan §5.1). */
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";
import { post } from "../api/client";
import type { SessionOut } from "../api/types";
import { landingFor, toSessionUser, useSessionControls } from "../app/session";
import { AccessibilityPanel } from "../components/Controls";
import { ErrorNotice, TextField } from "../components/Forms";
import { HeroBanner, PrimaryButton } from "../design";
import { PublicFrame } from "./auth/PublicFrame";

export function StartPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { apply } = useSessionControls();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await post<SessionOut>("/auth/login", { username, password });
      apply(s);
      if (s.user) navigate(landingFor(toSessionUser(s.user)), { replace: true });
    } catch (err) {
      setError(err);
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicFrame>
      <HeroBanner title={t("placeholder.title")} body={t("app.tagline")} headingLevel={1} />
      <section className="fb-card" aria-labelledby="signin-title">
        <h2 id="signin-title" className="fb-card__title">
          {t("auth.signIn")}
        </h2>
        <form onSubmit={onSubmit} className="fb-form" noValidate>
          <TextField
            label={t("auth.username")}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <TextField
            label={t("auth.password")}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <ErrorNotice error={error} />
          <PrimaryButton type="submit" disabled={busy || !username || !password}>
            {t("auth.signIn")}
          </PrimaryButton>
        </form>
        <ul className="fb-links">
          <li>
            <Link to="/redeem">{t("auth.haveInvite")}</Link>
          </li>
          <li>
            <Link to="/reset">{t("auth.haveReset")}</Link>
          </li>
        </ul>
        <p className="fb-setting__hint">{t("auth.forgotHint")}</p>
      </section>
      <AccessibilityPanel />
      {import.meta.env.DEV && <Link to="/dev/gallery">{t("placeholder.gallery")}</Link>}
    </PublicFrame>
  );
}
