/**
 * Redeem an invitation code (Plan §5.1; D29): enter the code, then choose a username,
 * display alias, language and password. Participants continue to onboarding consent.
 */
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { ApiError, post } from "../../api/client";
import type { CodeInfo, SessionOut } from "../../api/types";
import { landingFor, toSessionUser, useSessionControls } from "../../app/session";
import { ErrorNotice, Notice, SelectField, TextField } from "../../components/Forms";
import { PrimaryButton } from "../../design";
import { LANGUAGES, isLanguage, type Language } from "../../i18n";
import { PublicFrame } from "./PublicFrame";

export function CodeStep({
  purpose,
  onValid,
}: {
  purpose: "invite" | "reset";
  onValid: (code: string, info: CodeInfo) => void;
}) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const info = await post<CodeInfo>("/auth/codes/inspect", { code });
      if (info.purpose !== purpose) {
        setError(new ApiError(400, "code.invalid"));
      } else onValid(code, info);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={onSubmit} className="fb-form" noValidate>
      <TextField
        label={t("auth.code")}
        hint={t("auth.codeHint")}
        autoComplete="one-time-code"
        autoCapitalize="characters"
        spellCheck={false}
        value={code}
        onChange={(e) => setCode(e.target.value)}
        required
      />
      <ErrorNotice error={error} />
      <PrimaryButton type="submit" disabled={busy || code.replace(/[^A-Za-z0-9]/g, "").length < 16}>
        {t("auth.checkCode")}
      </PrimaryButton>
    </form>
  );
}

export function RedeemPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { apply } = useSessionControls();
  const [code, setCode] = useState<string | null>(null);
  const [info, setInfo] = useState<CodeInfo | null>(null);
  const [username, setUsername] = useState("");
  const [alias, setAlias] = useState("");
  // Follows the page language until the person picks one explicitly.
  const [languageChoice, setLanguage] = useState<Language | null>(null);
  const language: Language = languageChoice ?? (isLanguage(i18n.language) ? i18n.language : "zh-CN");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const mismatch = confirm.length > 0 && confirm !== password;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (mismatch || !code) return;
    setBusy(true);
    setError(null);
    try {
      const s = await post<SessionOut>("/auth/redeem", {
        code,
        username,
        display_alias: alias,
        language,
        password,
      });
      apply(s);
      void i18n.changeLanguage(language);
      if (s.user) navigate(landingFor(toSessionUser(s.user)), { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicFrame>
      <section className="fb-card" aria-labelledby="redeem-title">
        <h1 id="redeem-title" className="fb-card__title">
          {t("auth.redeemTitle")}
        </h1>
        {!info || !code ? (
          <>
            <p>{t("auth.redeemIntro")}</p>
            <CodeStep
              purpose="invite"
              onValid={(c, i) => {
                setCode(c);
                setInfo(i);
              }}
            />
          </>
        ) : (
          <form onSubmit={onSubmit} className="fb-form" noValidate>
            <Notice>{t("auth.inviteFor", { role: t(`role.${info.role}`) })}</Notice>
            <TextField
              label={t("auth.chooseUsername")}
              hint={t("auth.usernameHint")}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
            <TextField
              label={t("auth.alias")}
              hint={t("auth.aliasHint")}
              value={alias}
              maxLength={40}
              onChange={(e) => setAlias(e.target.value)}
              required
            />
            <SelectField
              label={t("language.label")}
              value={language}
              onChange={(v) => isLanguage(v) && setLanguage(v)}
              options={LANGUAGES.map((l) => ({
                value: l,
                label: t(`language.${l}`),
              }))}
            />
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
            <PrimaryButton
              type="submit"
              disabled={busy || !username || !alias.trim() || !password || mismatch || !confirm}
            >
              {t("auth.createAccount")}
            </PrimaryButton>
          </form>
        )}
      </section>
    </PublicFrame>
  );
}
