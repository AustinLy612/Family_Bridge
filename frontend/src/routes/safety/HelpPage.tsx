/**
 * Participant help screen (Plan §5.7; Phase 2 task 3). Reachable from every participant screen
 * (sidebar/tab bar and the header "Get help" link) and opened by the safety flow.
 * After a stop it shows the stop notice first. It never says why, never shows scores, and does
 * not mention who may read what was written (D40).
 */
import { LifeBuoy } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";
import { useHelpPage, type HelpLocationState } from "../../app/safety";
import { ErrorNotice, Notice } from "../../components/Forms";
import { ContentSections, HelpContacts } from "../../components/Safety";
import { Page } from "../Page";

export function HelpPage() {
  const { t } = useTranslation();
  const q = useHelpPage();
  const state = (useLocation().state ?? {}) as HelpLocationState;
  const stopped = state.safety === "stop";
  const headingRef = useRef<HTMLHeadingElement>(null);
  const doc = q.data?.document;

  // After the safety flow brings someone here, move focus to the first message.
  useEffect(() => {
    if (state.safety && doc) headingRef.current?.focus();
  }, [state.safety, doc]);

  return (
    <Page title={t("nav.help")} subtitle={t("safety.helpSubtitle")} icon={<LifeBuoy size={22} />}>
      <div className="fb-stack">
        <ErrorNotice error={q.error} />
        {doc && stopped && (
          <section className="fb-card fb-care-card" aria-labelledby="stop-title">
            <h2 id="stop-title" ref={headingRef} tabIndex={-1} className="fb-card__title">
              {doc.stop_notice.title}
            </h2>
            <p>{doc.stop_notice.body}</p>
          </section>
        )}
        {q.data && <HelpContacts help={q.data.site} />}
        {doc && (
          <section className="fb-card" aria-labelledby={stopped ? undefined : "help-doc-title"}>
            {!stopped && (
              <h2
                id="help-doc-title"
                ref={state.safety ? headingRef : undefined}
                tabIndex={-1}
                className="visually-hidden"
              >
                {t("nav.help")}
              </h2>
            )}
            {doc.approval !== "approved" && <Notice tone="warn">{t("safety.draftNotice")}</Notice>}
            <ContentSections sections={doc.sections} />
          </section>
        )}
      </div>
    </Page>
  );
}
