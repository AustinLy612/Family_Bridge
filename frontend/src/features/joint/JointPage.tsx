/**
 * Joint sessions for a participant (Plan §5.9 lifecycle 2): neutral invitation cards with the
 * activity, its skill objective and duration, "you can say no or stop anytime", and two equal
 * buttons. No reason is asked; a partner's decline is never attributed (§9.1C).
 * A solo rehearsal of the placeholder activity is available any time (§5.2).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, HeartHandshake, Target } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";
import { bi, joint, type MySession } from "../../api/joint";
import { ROLE_HOME, useSession } from "../../app/session";
import { ErrorNotice, Notice } from "../../components/Forms";
import { Chip, DecisionButtons, DetailBar, PrimaryButton } from "../../design";
import { Section } from "../lessons/common";
import { Page } from "../../routes/Page";
import "./joint.css";

const OPEN = new Set(["invited", "accepted", "ready", "active"]);
const PAST_SHOWN = 5;

export function JointPage() {
  const { t } = useTranslation();
  const user = useSession();
  const navigate = useNavigate();
  const home = user?.role === "caregiver" ? ROLE_HOME.caregiver : ROLE_HOME.adolescent;
  const q = useQuery({ queryKey: ["joint", "mine"], queryFn: joint.mine, refetchInterval: 30_000 });
  const [error, setError] = useState<unknown>(null);
  const [showAllPast, setShowAllPast] = useState(false);
  const sessions = (q.data?.sessions ?? []).filter((s) => s.mode === "joint");
  const open = sessions.filter((s) => OPEN.has(s.status));
  const past = sessions.filter((s) => !OPEN.has(s.status));

  async function solo() {
    setError(null);
    try {
      const s = await joint.solo();
      navigate(`${home}/joint/${s.id}`);
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Page title={t("nav.joint")} subtitle={t("joint.subtitle")} icon={<HeartHandshake size={22} />}>
      <div className="fb-stack">
        <ErrorNotice error={error ?? q.error} />
        <Notice>{t("joint.optional")}</Notice>
        <Section title={t("joint.invitations")}>
          {q.isSuccess && open.length === 0 && <p className="fb-setting__hint">{t("joint.none")}</p>}
          {open.map((s) => (
            <InvitationCard key={s.id} s={s} href={`${home}/joint/${s.id}`} onError={setError} />
          ))}
        </Section>
        <Section title={t("joint.solo.title")}>
          <p className="fb-setting__hint">{t("joint.solo.hint")}</p>
          <div>
            <PrimaryButton variant="secondary" onClick={() => void solo()}>
              {t("joint.solo.start")}
            </PrimaryButton>
          </div>
        </Section>
        {past.length > 0 && (
          <Section title={t("joint.past")}>
            <ul className="fb-joint-past">
              {(showAllPast ? past : past.slice(0, PAST_SHOWN)).map((s) => (
                <li key={s.id}>
                  <PastLine s={s} />
                </li>
              ))}
            </ul>
            {past.length > PAST_SHOWN && (
              <div>
                <PrimaryButton variant="secondary" onClick={() => setShowAllPast((v) => !v)}>
                  {showAllPast ? t("joint.showFewer") : t("joint.showAll", { count: past.length })}
                </PrimaryButton>
              </div>
            )}
          </Section>
        )}
      </div>
    </Page>
  );
}

function When({ s }: { s: MySession }) {
  const { t, i18n } = useTranslation();
  const fmt = (d: string) =>
    new Date(d).toLocaleString(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  return <>{t("joint.window", { from: fmt(s.opens_at), to: fmt(s.closes_at) })}</>;
}

function InvitationCard({ s, href, onError }: { s: MySession; href: string; onError: (e: unknown) => void }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const lang = i18n.language;
  async function respond(r: "accepted" | "declined") {
    onError(null);
    try {
      await joint.respond(s.id, r);
      await qc.invalidateQueries({ queryKey: ["joint"] });
    } catch (err) {
      onError(err);
    }
  }
  return (
    <article
      className="fb-card fb-stack"
      data-testid="joint-invitation"
      data-session={s.id}
      aria-label={bi(s.episode?.title, lang)}
    >
      <h3 className="fb-card__title">{bi(s.episode?.title, lang)}</h3>
      <DetailBar
        items={[
          { icon: <Target size={18} />, label: t("joint.objective"), value: bi(s.episode?.objective, lang) },
          {
            icon: <Clock size={18} />,
            label: t("joint.duration"),
            value: t("joint.minutes", { n: s.episode?.estimated_minutes ?? 0 }),
          },
        ]}
      />
      <p className="fb-setting__hint">
        <When s={s} />
      </p>
      <p>{t("joint.canStop")}</p>
      {s.can_respond ? (
        <DecisionButtons
          acceptLabel={t("joint.accept")}
          declineLabel={t("joint.decline")}
          onAccept={() => void respond("accepted")}
          onDecline={() => void respond("declined")}
        />
      ) : s.can_join ? (
        <div>
          <Link className="fb-btn fb-btn--primary" to={href}>
            {t("joint.join")}
          </Link>
        </div>
      ) : (
        <Chip tone="outline">{t(`joint.status.${s.status}`)}</Chip>
      )}
    </article>
  );
}

function PastLine({ s }: { s: MySession }) {
  const { t, i18n } = useTranslation();
  const date = new Date(s.opens_at).toLocaleDateString(i18n.language, { dateStyle: "medium" });
  return (
    <>
      <span className="fb-joint-past__title">{bi(s.episode?.title, i18n.language)}</span>
      <span className="fb-joint-past__date">{date}</span>
      <Chip tone="outline">{t(`joint.status.${s.status}`)}</Chip>
    </>
  );
}
