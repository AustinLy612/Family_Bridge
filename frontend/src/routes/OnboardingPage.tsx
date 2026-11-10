/**
 * Participant onboarding consent (Plan §5.2; D31, D32). Each participant does this separately,
 * in their own language. Required items start unticked (affirmative consent); the optional
 * research switch starts ON and is clearly visible (D32). Declining a required item cannot
 * complete onboarding; the screen asks the participant to talk to their therapist (O5).
 */
import * as Switch from "@radix-ui/react-switch";
import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate } from "react-router";
import { get, post } from "../api/client";
import type { ConsentCategory, OnboardingOut, UserOut } from "../api/types";
import { isParticipantRole, landingFor, toSessionUser, useSessionControls } from "../app/session";
import { ErrorNotice, Notice } from "../components/Forms";
import { ContentSections, HelpContacts } from "../components/Safety";
import { PrimaryButton } from "../design";
import { isLanguage } from "../i18n";
import { PublicFrame } from "./auth/PublicFrame";
import { useTaskOutcome } from "../app/research";

function ConsentItem({
  cat,
  value,
  onChange,
}: {
  cat: ConsentCategory;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <div className={`fb-consent${cat.required ? "" : " fb-consent--optional"}`}>
      <div className="fb-consent__text">
        <label htmlFor={id} className="fb-setting__label">
          {cat.title}
        </label>
        <span className="fb-setting__hint">{cat.summary}</span>
        <span className="fb-consent__tag">
          {cat.required ? t("onboarding.required") : t("onboarding.optional")}
        </span>
      </div>
      {cat.required ? (
        <input
          id={id}
          type="checkbox"
          className="fb-checkbox"
          checked={value}
          onChange={(e) => onChange(e.target.checked)}
        />
      ) : (
        <Switch.Root id={id} className="fb-switch" checked={value} onCheckedChange={onChange}>
          <Switch.Thumb className="fb-switch__thumb" />
        </Switch.Root>
      )}
    </div>
  );
}

export function OnboardingPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { user, loading, setUser, logout } = useSessionControls();
  const language = isLanguage(i18n.language) ? i18n.language : "zh-CN";
  const q = useQuery({
    queryKey: ["onboarding", language],
    queryFn: () => get<OnboardingOut>(`/onboarding?language=${encodeURIComponent(language)}`),
    enabled: !!user && isParticipantRole(user.role),
  });
  const [changes, setChanges] = useState<Record<string, boolean>>({});
  const [declined, setDeclined] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  // usability (§8.4): leaving onboarding before accepting counts as abandoned
  const taskDone = useTaskOutcome("onboarding", !!user && landingFor(user) === "/onboarding");

  if (loading) return null;
  if (!user) return <Navigate to="/" replace />;
  if (landingFor(user) !== "/onboarding") return <Navigate to={landingFor(user)} replace />;

  const doc = q.data?.document;
  // Initial positions come from the document: required unticked, research ON (D32).
  const decisions: Record<string, boolean> = Object.fromEntries(
    (doc?.categories ?? []).map((c) => [c.id, changes[c.id] ?? (c.required ? false : c.default)]),
  );
  const missingRequired = doc ? doc.categories.filter((c) => c.required && !decisions[c.id]) : [];

  async function accept() {
    if (!doc) return;
    if (missingRequired.length) {
      setDeclined(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const u = await post<UserOut>("/onboarding/accept", {
        version: doc.version,
        language: doc.language,
        decisions,
      });
      taskDone();
      setUser(u);
      navigate(landingFor(toSessionUser(u)), { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicFrame wide>
      <section className="fb-card" aria-labelledby="onb-title">
        <h1 id="onb-title" className="fb-card__title">
          {t("onboarding.title", { alias: user.displayAlias })}
        </h1>
        <p>{t("onboarding.intro")}</p>
        {doc?.approval !== "approved" && doc && <Notice tone="warn">{t("onboarding.draftNotice")}</Notice>}
        {q.isError && <ErrorNotice error={q.error} />}
        {doc && <ContentSections sections={doc.sections} />}
      </section>

      {q.data && <HelpContacts help={q.data.help} />}

      {doc && (
        <section className="fb-card" aria-labelledby="choices-title">
          <h2 id="choices-title" className="fb-card__title">
            {t("onboarding.choices")}
          </h2>
          {doc.categories.map((c) => (
            <ConsentItem
              key={c.id}
              cat={c}
              value={!!decisions[c.id]}
              onChange={(v) => {
                setChanges((d) => ({ ...d, [c.id]: v }));
                setDeclined(false);
              }}
            />
          ))}
          {declined && (
            <div role="alert" className="fb-notice fb-notice--warn">
              <p>{t("onboarding.declined")}</p>
            </div>
          )}
          <ErrorNotice error={error} />
          <div className="fb-actions">
            <PrimaryButton type="button" onClick={() => void accept()} disabled={busy}>
              {t("onboarding.accept")}
            </PrimaryButton>
            <button type="button" className="fb-btn fb-btn--secondary" onClick={() => setDeclined(true)}>
              {t("onboarding.notNow")}
            </button>
          </div>
          <button
            type="button"
            className="fb-linkbtn"
            onClick={() => void logout().finally(() => navigate("/", { replace: true }))}
          >
            {t("nav.logout")}
          </button>
        </section>
      )}
    </PublicFrame>
  );
}
