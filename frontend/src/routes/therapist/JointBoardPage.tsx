/**
 * Therapist joint-session board (Plan §5.8 "Joint-session board", §5.9): schedule an episode
 * version for a suitable pair in a window; live status of scheduled and active rooms (presence,
 * current step, who has acted) with pause / resume / safety pause / end, and reset for demo
 * families. Declines are shown here only (§9.1C). Planned worlds are listed as "coming soon".
 * The board refreshes every few seconds; it is not a live monitoring service.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { HeartHandshake } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { bi, joint, type BoardSession, type ControlAction, type GroupJoint } from "../../api/joint";
import { ErrorNotice, Notice, SelectField, TextField } from "../../components/Forms";
import { Chip, PrimaryButton } from "../../design";
import { Section } from "../../features/lessons/common";
import { Page } from "../Page";
import { GroupSelect } from "./common";
import { useGroupChoice } from "./groups";
import "../../features/joint/joint.css";
import "./therapist.css";

export function JointBoardPage() {
  const { t } = useTranslation();
  const { groups, list, groupId, setGroupId } = useGroupChoice();
  const q = useQuery({
    queryKey: ["joint-board", groupId],
    queryFn: () => joint.group(groupId ?? ""),
    enabled: !!groupId,
    refetchInterval: 5_000,
  });
  return (
    <Page title={t("nav.joint")} subtitle={t("therapist.joint.subtitle")} icon={<HeartHandshake size={22} />}>
      <div className="fb-stack">
        <ErrorNotice error={groups.error ?? q.error} />
        {groups.isSuccess && list.length === 0 && <p>{t("therapist.diary.noGroups")}</p>}
        <GroupSelect groups={list} value={groupId} onChange={setGroupId} />
        {q.data && groupId && (
          <>
            <ScheduleForm groupId={groupId} data={q.data} />
            <Sessions groupId={groupId} sessions={q.data.sessions} />
            <Catalog data={q.data} />
          </>
        )}
      </div>
    </Page>
  );
}

function localInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function ScheduleForm({ groupId, data }: { groupId: string; data: GroupJoint }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [familyId, setFamilyId] = useState(data.families[0]?.id ?? "");
  const family = data.families.find((f) => f.id === familyId);
  const pairs = family?.pairs ?? [];
  const [caregiverId, setCaregiverId] = useState("");
  const episodes = useMemo(
    () => data.episodes.filter((e) => e.assignable_families.includes(familyId)),
    [data.episodes, familyId],
  );
  const [episodeKey, setEpisodeKey] = useState("");
  const now = new Date();
  const [opens, setOpens] = useState(localInput(now));
  const [closes, setCloses] = useState(localInput(new Date(now.getTime() + 2 * 86_400_000)));
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);

  const suitable = pairs.filter((p) => p.suitable);
  const carer = caregiverId || suitable[0]?.caregiver_id || "";
  const epKey = episodeKey || (episodes[0] ? `${episodes[0].id}@${episodes[0].version}` : "");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setDone(false);
    const [id, version] = epKey.split("@");
    try {
      await joint.schedule(groupId, {
        family_id: familyId,
        caregiver_id: carer,
        episode_id: id ?? "",
        episode_version: Number(version),
        opens_at: new Date(opens).toISOString(),
        closes_at: new Date(closes).toISOString(),
      });
      setDone(true);
      await qc.invalidateQueries({ queryKey: ["joint-board", groupId] });
    } catch (err) {
      setError(err);
    }
  }

  return (
    <section className="fb-card fb-stack" aria-labelledby="joint-schedule">
      <h2 id="joint-schedule" className="fb-card__title">
        {t("therapist.joint.schedule")}
      </h2>
      <p className="fb-setting__hint">{t("therapist.joint.scheduleHint")}</p>
      <form className="fb-stack" onSubmit={(e) => void submit(e)} noValidate>
        <SelectField
          label={t("therapist.joint.family")}
          value={familyId}
          onChange={(v) => {
            setFamilyId(v);
            setCaregiverId("");
            setEpisodeKey("");
          }}
          options={data.families.map((f) => ({ value: f.id, label: f.label }))}
        />
        {pairs.length > 0 && suitable.length === 0 && <Notice>{t("therapist.joint.noSuitable")}</Notice>}
        {suitable.length > 0 && (
          <SelectField
            label={t("therapist.joint.pair")}
            value={carer}
            onChange={setCaregiverId}
            options={suitable.map((p) => ({
              value: p.caregiver_id,
              label: `${p.adolescent_alias ?? ""} + ${p.caregiver_alias}`,
            }))}
          />
        )}
        {episodes.length === 0 ? (
          <Notice>{t("therapist.joint.noEpisodes")}</Notice>
        ) : (
          <SelectField
            label={t("therapist.joint.episode")}
            value={epKey}
            onChange={setEpisodeKey}
            options={episodes.map((e) => ({
              value: `${e.id}@${e.version}`,
              label: `${bi(e.title, i18n.language)} (v${e.version}${e.status === "demo" ? `, ${t("therapist.joint.demoOnly")}` : ""})`,
            }))}
          />
        )}
        <div className="fb-joint-dates">
          <TextField
            label={t("therapist.joint.opens")}
            type="datetime-local"
            value={opens}
            onChange={(e) => setOpens(e.target.value)}
          />
          <TextField
            label={t("therapist.joint.closes")}
            type="datetime-local"
            value={closes}
            onChange={(e) => setCloses(e.target.value)}
          />
        </div>
        <ErrorNotice error={error} />
        {done && <Notice>{t("therapist.joint.scheduled")}</Notice>}
        <div>
          <PrimaryButton type="submit" disabled={!carer || !epKey}>
            {t("therapist.joint.invite")}
          </PrimaryButton>
        </div>
      </form>
    </section>
  );
}

const CONTROLS: Record<string, ControlAction[]> = {
  lobby: ["pause", "safety_pause", "terminate"],
  running: ["pause", "safety_pause", "terminate"],
  paused: ["resume", "safety_pause", "terminate"],
  paused_safety: ["resume", "terminate"],
};

function Sessions({ groupId, sessions }: { groupId: string; sessions: BoardSession[] }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const fmt = (d: string) =>
    new Date(d).toLocaleString(i18n.language, { dateStyle: "medium", timeStyle: "short" });

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await qc.invalidateQueries({ queryKey: ["joint-board", groupId] });
    } catch (err) {
      setError(err);
    }
  }

  const person = (p: BoardSession["adolescent"], live: boolean) =>
    p && (
      <span>
        {p.alias} <Chip tone="outline">{t(`therapist.joint.response.${p.response ?? "none"}`)}</Chip>{" "}
        {live && <Chip tone="outline">{t(p.present ? "therapist.joint.here" : "therapist.joint.away")}</Chip>}
      </span>
    );

  return (
    <Section title={t("therapist.joint.sessions")}>
      <ErrorNotice error={error} />
      {sessions.length === 0 ? (
        <p className="fb-setting__hint">{t("therapist.joint.noSessions")}</p>
      ) : (
        <table className="fb-joint-table" data-testid="joint-board">
          <thead>
            <tr>
              <th scope="col">{t("therapist.joint.episode")}</th>
              <th scope="col">{t("therapist.joint.people")}</th>
              <th scope="col">{t("therapist.joint.status")}</th>
              <th scope="col">{t("therapist.joint.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => {
              const b = s.board;
              const live = s.status === "active" || s.status === "invited";
              const phase = b?.phase ?? "";
              const controls =
                s.status === "active" || (s.status === "invited" && phase !== "lobby")
                  ? (CONTROLS[phase] ?? [])
                  : [];
              return (
                <tr key={s.id} data-testid="joint-session-row">
                  <td>
                    <strong>{bi(s.episode?.title, i18n.language)}</strong>
                    <br />
                    <span className="fb-setting__hint">
                      {fmt(s.opens_at)} – {fmt(s.closes_at)}
                    </span>
                  </td>
                  <td>
                    {person(s.adolescent, live)}
                    <br />
                    {person(s.caregiver, live)}
                  </td>
                  <td>
                    {s.time_passed
                      ? t("therapist.joint.state.time_passed")
                      : t(`therapist.joint.state.${s.status}`)}
                    {b &&
                      (s.status === "active" || phase !== "lobby") &&
                      s.status !== "completed" &&
                      s.status !== "ended" && (
                        <>
                          <br />
                          <span>
                            {t(`therapist.joint.phase.${phase}`)}
                            {b.pause_by ? ` · ${t(`therapist.joint.pauseBy.${b.pause_by}`)}` : ""}
                          </span>
                          {b.step_id && (
                            <>
                              <br />
                              <span className="fb-setting__hint">
                                {t("therapist.joint.step", { n: b.step_index + 1, total: b.step_count })} ·{" "}
                                {t(`joint.step.${b.step_type}`)} ·{" "}
                                {Object.entries(b.acted)
                                  .filter(([, v]) => v)
                                  .map(([r]) => t(`therapist.joint.role.${r}`))
                                  .join(", ") || t("therapist.joint.nobodyYet")}
                              </span>
                            </>
                          )}
                        </>
                      )}
                  </td>
                  <td>
                    <div className="fb-joint-actions">
                      {controls.map((a) => (
                        <PrimaryButton
                          key={a}
                          variant="secondary"
                          onClick={() => void run(() => joint.control(s.id, a))}
                        >
                          {t(`therapist.joint.control.${a}`)}
                        </PrimaryButton>
                      ))}
                      {s.status === "invited" && phase === "lobby" && (
                        <PrimaryButton variant="secondary" onClick={() => void run(() => joint.cancel(s.id))}>
                          {t("therapist.joint.cancel")}
                        </PrimaryButton>
                      )}
                      {(s.status === "completed" || s.status === "ended") && (
                        <Link to={`/therapist/joint/${s.id}`}>{t("therapist.joint.summary")}</Link>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Section>
  );
}

function Catalog({ data }: { data: GroupJoint }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  return (
    <Section title={t("therapist.joint.comingSoon")}>
      <p className="fb-setting__hint">{t("therapist.joint.comingSoonHint")}</p>
      <ul className="fb-joint-past" data-testid="joint-catalog">
        {data.catalog.map((w) =>
          w.levels.map((lv) => (
            <li key={`${w.id}-${lv.level}`}>
              <strong>{t("therapist.joint.worldLevel", { world: bi(w.name, lang), level: lv.level })}</strong>
              : {bi(lv.focus, lang)} ·{" "}
              {t("therapist.joint.minutesRange", { from: lv.target_minutes[0], to: lv.target_minutes[1] })}
            </li>
          )),
        )}
      </ul>
    </Section>
  );
}
