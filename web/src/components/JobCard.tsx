import { ExternalLink } from "lucide-react";
import type { Job } from "../lib/types";
import { fmtDateTime, fmtRelative, sourceTone } from "../lib/format";
import { CategoryBadge, ClosedMark } from "./Badge";
import { CompanyLogo } from "./CompanyLogo";

/**
 * One posting, as a card.
 *
 * Taller and narrower than it started: a wide gutter between the columns
 * takes width off each card, and a 15rem floor plus a third line for both the
 * title and the reasoning spends the height on text that was being clipped
 * rather than on padding.
 *
 * The table it replaces was eight columns of the same six values, and it read
 * as what it is - a SELECT. A card puts the two things a reader actually
 * scans for, the employer and the role, at the top left where the eye starts,
 * and gives the employer a mark instead of a string. Everything the table
 * carried is still here; it is arranged rather than tabulated.
 *
 * The grid is shared with the skeleton so the two never drift apart.
 */
/*
  Three across is the shape asked for, but only where three of these fit.
  Measured: the sidebar takes 256px and the main column 48-64px of padding, so
  a 1100px window leaves 796px - three 256px cards, in which the employer name
  truncates to "TELUS Digital A..." and the footer wraps onto a second line.
  At xl the same three get ~310px and the name survives; below it, two.
*/
/*
  40px between the columns against 56px to the page edge. The gutter used to
  be the wider of the two, which read as three cards drifting apart inside a
  frame too tight for them. The card keeps its 384px either way: the 24px the
  gutter gives up is exactly what the margins take.
*/
export const JOB_GRID =
  "grid grid-cols-1 gap-x-10 gap-y-8 md:grid-cols-2 xl:grid-cols-3";

export function JobCard({ job }: { job: Job }) {
  const closed = Boolean(job.closed_at);

  return (
    /*
      relative, because the title's link is stretched over the whole card by
      the ::after below - a card is a target, and asking someone to hit the
      title text inside it is asking them to aim. The two blocks that carry
      their own hover (the reasoning, and the badges with their tooltips) lift
      themselves back above it with z-10.
    */
    <article className="group relative flex h-full min-h-[15rem] flex-col border border-line bg-white/[0.01] transition-colors hover:border-line-strong hover:bg-white/[0.03]">
      <div className="flex items-start gap-4 p-5 pb-4">
        <CompanyLogo
          company={job.company}
          logoUrl={job.company_logo_url}
          dimmed={closed}
          className="size-16"
        />

        <div className="min-w-0 flex-1 pt-0.5">
          <p className="truncate text-sm font-medium text-ink" title={job.company ?? undefined}>
            {job.company ?? "—"}
          </p>
          <p className="mt-1 flex items-center gap-1.5 font-mono text-[11px] whitespace-nowrap text-muted-2">
            <span className={sourceTone(job.source_site)}>{job.source_label}</span>
            {job.location && (
              <>
                <span>·</span>
                <span className="truncate">{job.location}</span>
              </>
            )}
          </p>
        </div>

        {/* The affordance stays visible rather than appearing on hover: the
            board already learned once that an invisible way out to the
            posting is one nobody finds. */}
        <ExternalLink
          size={13}
          strokeWidth={2}
          className="mt-1 shrink-0 text-muted-3 transition-colors group-hover:text-ink"
        />
      </div>

      <h3 className="px-5">
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          title={closed ? "İlan yayından kalkmış - sayfa hâlâ açılabilir" : job.job_title}
          className="after:absolute after:inset-0"
        >
          {/* The clamp lives on the span, not the anchor: -webkit-line-clamp
              hides overflow on the element that carries it, ::after included,
              and the stretched link would be clipped away with the text. */}
          <span
            className={`line-clamp-3 text-[13px] leading-snug font-medium underline-offset-2 transition-colors group-hover:underline ${
              // Dimmed rather than struck through: a closed posting is still
              // worth reading, it just cannot be applied to any more.
              closed ? "text-muted-2" : "text-ink-2 group-hover:text-ink"
            }`}
          >
            {job.job_title}
          </span>
        </a>
      </h3>

      {/*
        The classifier's reasoning, on the card rather than behind a tooltip.
        docs/dashboard.md rule 5: a verdict should be arguable, and this is
        the page you come to when one looks wrong - a reason you have to hover
        to read is a reason nobody audits. Two lines here, the rest on hover.
      */}
      <p
        className="relative z-10 mt-2.5 line-clamp-3 px-5 text-[11px] leading-relaxed text-muted-2"
        title={job.category_reason ?? undefined}
      >
        {job.category_reason ?? "—"}
      </p>

      <div className="relative z-10 mt-auto flex flex-wrap items-center gap-2 border-t border-line-soft px-5 py-3.5">
        <CategoryBadge
          category={job.job_category}
          label={job.category_label}
          reason={job.category_reason}
        />
        {job.job_type_label && (
          <span className="font-mono text-[11px] whitespace-nowrap text-muted">
            {job.job_type_label}
          </span>
        )}
        <ClosedMark closedAt={job.closed_at} when={fmtRelative(job.closed_at)} />
        <span
          className="ml-auto font-mono text-[11px] whitespace-nowrap text-muted-2"
          title={fmtDateTime(job.created_at)}
        >
          {fmtRelative(job.created_at)}
        </span>
      </div>
    </article>
  );
}
