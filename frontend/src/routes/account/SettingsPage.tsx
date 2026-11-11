/**
 * Account settings (Phase 1 task 7): alias, language and accessibility (saved on the account by
 * ServerPrefsSync), password change, research consent (D32), sign out everywhere, and the
 * "Who can see my data" card (reachable only from settings since D92, Plan §5.2).
 */
import * as Switch from "@radix-ui/react-switch";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";
import { patch, post, put } from "../../api/client";
import { get } from "../../api/client";
import type { ConsentState, UserOut } from "../../api/types";
import { isParticipant } from "../../app/nav";
import { ROLE_HOME, useSessionControls } from "../../app/session";
import { AccessibilityPanel } from "../../components/Controls";
import { ErrorNotice, Notice, TextField } from "../../components/Forms";
import { PrimaryButton } from "../../design";
import { Page } from "../Page";

function ProfileCard() {
  const { t } = useTranslation();
  const { user, setUser } = useSessionControls();
  const [alias, setAlias] = useState(user?.displayAlias ?? "");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      setUser(await patch<UserOut>("/me", { display_alias: alias }));
      setSaved(true);
    } catch (err) {
      setError(err);
    }
  }
  return (
    <section className="fb-card" aria-labelledby="profile-title">
      <h2 id="profile-title" className="fb-card__title">
        {t("account.profile")}
      </h2>
      <p className="fb-setting__hint">{t("account.username", { username: user?.username ?? "" })}</p>
      <form onSubmit={onSubmit} className="fb-form" noValidate>
        <TextField
          label={t("auth.alias")}
          hint={t("auth.aliasHint")}
          value={alias}
          maxLength={40}
          onChange={(e) => {
            setAlias(e.target.value);
            setSaved(false);
          }}
        />
        <ErrorNotice error={error} />
        {saved && <Notice>{t("account.saved")}</Notice>}
        <PrimaryButton type="submit" variant="secondary" disabled={!alias.trim()}>
          {t("account.save")}
        </PrimaryButton>
      </form>
    </section>
  );
}

function PasswordCard() {
  const { t } = useTranslation();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const mismatch = confirm.length > 0 && confirm !== next;
  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (mismatch) return;
    setError(null);
    try {
      await post("/auth/password", {
        current_password: current,
        new_password: next,
      });
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setError(err);
    }
  }
  return (
    <section className="fb-card" aria-labelledby="pw-title">
      <h2 id="pw-title" className="fb-card__title">
        {t("account.changePassword")}
      </h2>
      <form onSubmit={onSubmit} className="fb-form" noValidate>
        <TextField
          label={t("account.currentPassword")}
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <TextField
          label={t("auth.newPassword")}
          hint={t("auth.passwordHint")}
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <TextField
          label={t("auth.confirmPassword")}
          type="password"
          autoComplete="new-password"
          value={confirm}
          error={mismatch ? t("auth.passwordMismatch") : undefined}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <ErrorNotice error={error} />
        {done && <Notice>{t("account.passwordChanged")}</Notice>}
        <PrimaryButton type="submit" variant="secondary" disabled={!current || !next || !confirm || mismatch}>
          {t("account.changePassword")}
        </PrimaryButton>
      </form>
    </section>
  );
}

function ResearchConsentCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const id = useId();
  const q = useQuery({
    queryKey: ["consent"],
    queryFn: () => get<ConsentState[]>("/me/consent"),
  });
  const [error, setError] = useState<unknown>(null);
  const research = q.data?.find((c) => c.category === "research_export");
  if (!research) return null;
  return (
    <section className="fb-card" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className="fb-card__title">
        {t("account.consentTitle")}
      </h2>
      <div className="fb-setting">
        <label htmlFor={id} className="fb-setting__label">
          {t("account.researchLabel")}
          <span className="fb-setting__hint">{t("account.researchHint")}</span>
        </label>
        <Switch.Root
          id={id}
          className="fb-switch"
          checked={research.granted}
          onCheckedChange={(v) => {
            setError(null);
            put<ConsentState[]>("/me/consent/research_export", { granted: v })
              .then((data) => {
                qc.setQueryData(["consent"], data);
                void qc.invalidateQueries({ queryKey: ["visibility"] });
              })
              .catch(setError);
          }}
        >
          <Switch.Thumb className="fb-switch__thumb" />
        </Switch.Root>
      </div>
      <ErrorNotice error={error} />
      <p className="fb-setting__hint">{t("account.requiredConsentHint")}</p>
    </section>
  );
}

/** "Who can see my data" lives in settings (D92), as a card like the others. */
function PrivacyCard({ href }: { href: string }) {
  const { t } = useTranslation();
  return (
    <section className="fb-card" aria-labelledby="privacy-title">
      <h2 id="privacy-title" className="fb-card__title">
        {t("nav.privacy")}
      </h2>
      <p className="fb-setting__hint">{t("account.privacyHint")}</p>
      <Link className="fb-btn fb-btn--secondary" to={href}>
        <ShieldCheck size={18} aria-hidden />
        {t("account.privacyOpen")}
      </Link>
    </section>
  );
}

function SessionsCard() {
  const { t } = useTranslation();
  const { apply } = useSessionControls();
  const navigate = useNavigate();
  return (
    <section className="fb-card" aria-labelledby="sessions-title">
      <h2 id="sessions-title" className="fb-card__title">
        {t("account.sessions")}
      </h2>
      <p className="fb-setting__hint">{t("account.logoutAllHint")}</p>
      <PrimaryButton
        variant="secondary"
        onClick={() => {
          void post("/auth/logout-all").finally(() => {
            apply({ user: null, csrf_token: null });
            navigate("/", { replace: true });
          });
        }}
      >
        {t("account.logoutAll")}
      </PrimaryButton>
    </section>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  const { user } = useSessionControls();
  if (!user) return null;
  const participant = isParticipant(user.role);
  return (
    <Page title={t("nav.settings")}>
      <div className="fb-stack">
        <ProfileCard />
        <AccessibilityPanel />
        {participant && (
          <>
            <ResearchConsentCard />
            <PrivacyCard href={`${ROLE_HOME[user.role]}/privacy`} />
          </>
        )}
        <PasswordCard />
        <SessionsCard />
      </div>
    </Page>
  );
}
