/**
 * The reference's status pill (500 ERROR / 429 LIMIT). Here it carries the
 * classifier's verdict, and `title` carries category_reason - the reasoning
 * is shown on purpose, so a posting sitting in the wrong bucket is obvious
 * the moment its reason reads wrong.
 */

const TONES = {
  accent: "border-line-strong bg-white/10 text-ink",
  neutral: "border-white/10 bg-white/[0.04] text-muted",
  warn: "border-amber-500/20 bg-amber-500/10 text-warn",
  bad: "border-red-500/20 bg-red-500/10 text-bad",
} as const;

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: React.ReactNode;
  tone?: keyof typeof TONES;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-block border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

/** NULL is its own state, not a missing value: the classifier has not looked
 *  at the posting yet, and the board shows it regardless of the filter. */
export function CategoryBadge({
  category,
  label,
  reason,
}: {
  category: string | null;
  label: string | null;
  reason: string | null;
}) {
  if (!category) {
    return (
      <Badge tone="warn" title="Sınıflandırıcı bu ilana henüz bakmadı - filtreden bağımsız gösteriliyor.">
        sınıflandırılmadı
      </Badge>
    );
  }
  return (
    <Badge tone={category === "it" ? "accent" : "neutral"} title={reason ?? undefined}>
      {label ?? category}
    </Badge>
  );
}
