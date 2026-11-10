/**
 * Help-screen building blocks (Plan §5.7; Phase 2 task 3). The help text itself is static,
 * versioned content (`content/help/{lang}.md`, served by GET /help); contacts and staffed hours
 * come from the site settings (O4). Nothing here promises monitoring or rescue (§9.1F).
 */
import { HeartHandshake } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import type { ContentSection, SiteHelp } from "../api/types";
import { useHelpPage } from "../app/safety";
import { Notice } from "./Forms";

/** Restricted Markdown sections (headings, paragraphs, bullets) parsed by the server. */
export function ContentSections({ sections }: { sections: ContentSection[] }) {
  return (
    <>
      {sections.map((s) => (
        <section key={s.heading} className="fb-consent-section">
          <h2>{s.heading}</h2>
          {s.blocks.map((b, i) =>
            b.type === "paragraph" ? (
              <p key={i}>{b.text}</p>
            ) : (
              <ul key={i}>
                {b.items.map((it) => (
                  <li key={it}>{it}</li>
                ))}
              </ul>
            ),
          )}
        </section>
      ))}
    </>
  );
}

const telHref = (phone: string) => `tel:${phone.replace(/[^\d+]/g, "")}`;

export function HelpContacts({ help }: { help: SiteHelp }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  return (
    <section className="fb-card" aria-labelledby="help-title">
      <h2 id="help-title" className="fb-card__title">
        {t("help.whereToGetHelp")}
      </h2>
      {help.placeholder && <Notice tone="warn">{t("help.placeholder")}</Notice>}
      {help.service_hours[lang] && <p>{help.service_hours[lang]}</p>}
      <ul className="fb-contact-list">
        {help.help_contacts.map((c, i) => (
          <li key={i}>
            <strong>{c.label[lang] ?? c.label.en}</strong>{" "}
            <a href={telHref(c.phone)} lang="en">
              {c.phone}
            </a>
            {c.hours[lang] && <span className="fb-setting__hint"> · {c.hours[lang]}</span>}
          </li>
        ))}
      </ul>
      <p className="fb-setting__hint">{t("help.emergency")}</p>
    </section>
  );
}

/**
 * Medium risk (Plan §5.7): a gentle, static card. No stop, no alarm colours, no mention of
 * scores or flags. Features show it inline when the server answers `care_card`.
 */
export function CareCard({ helpHref, onDismiss }: { helpHref: string; onDismiss?: () => void }) {
  const { t } = useTranslation();
  const q = useHelpPage();
  const card = q.data?.document.care_card;
  return (
    <aside className="fb-card fb-care-card" aria-labelledby="care-card-title">
      <span className="fb-icon-tile" aria-hidden>
        <HeartHandshake size={22} />
      </span>
      <div className="fb-stack">
        <h2 id="care-card-title" className="fb-card__title">
          {card?.title ?? t("nav.help")}
        </h2>
        {card && <p>{card.body}</p>}
        {q.data && <HelpContacts help={q.data.site} />}
        <div className="fb-actions">
          <Link className="fb-btn fb-btn--secondary" to={helpHref}>
            {t("safety.openHelp")}
          </Link>
          {onDismiss && (
            <button type="button" className="fb-btn fb-btn--secondary" onClick={onDismiss}>
              {t("safety.keepGoing")}
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
