/** Read-only diary values (own entries, earlier versions, share previews, shared items). */
import { useTranslation } from "react-i18next";
import type { DiaryTemplate, DiaryValue, DiaryValues, RenderedItem } from "../../api/diary";
import { allFields, type useValueText } from "./util";

export function ValueList({
  template,
  values,
  note,
  text,
}: {
  template: DiaryTemplate;
  values: DiaryValues;
  note: string | null;
  text: ReturnType<typeof useValueText>;
}) {
  const { t } = useTranslation();
  const fields = allFields(template).filter((f) => (f.type === "note" ? !!note : values[f.id] !== undefined));
  if (!fields.length) return <p>{t("diary.nothingAnswered")}</p>;
  return (
    <dl className="fb-diary-values">
      {fields.map((f) => (
        <div key={f.id} style={{ display: "contents" }}>
          <dt>{f.label}</dt>
          <dd>{f.type === "note" ? note : text(f, values[f.id] as DiaryValue)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function RenderedValues({ items }: { items: RenderedItem[] }) {
  const { t } = useTranslation();
  return (
    <dl className="fb-diary-values">
      {items.map((i) => (
        <div key={i.field_id} style={{ display: "contents" }}>
          <dt>{i.label}</dt>
          <dd>
            {i.display ??
              (i.type === "scale"
                ? t("diary.scaleValue", { value: i.value })
                : i.type === "boolean"
                  ? i.value
                    ? t("diary.yes")
                    : t("diary.no")
                  : String(i.value))}
          </dd>
        </div>
      ))}
    </dl>
  );
}
