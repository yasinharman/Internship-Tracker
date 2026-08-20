import {
  BarController,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
  type ChartData,
  type ChartOptions,
} from "chart.js";
import { Chart } from "react-chartjs-2";
import type { Stats } from "../lib/types";
import { fmtDayMonth, fmtNumber } from "../lib/format";

ChartJS.register(
  BarController,
  LineController,
  BarElement,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Filler,
  Tooltip,
);

/**
 * The reference draws this with Chart.js on a canvas, and its config is
 * ported here value for value.
 *
 * Worth knowing: the canvas is the ONLY genuinely coloured thing on the
 * board. The page's CSS override rewrites every blue and emerald in the DOM
 * to a warm neutral, but it cannot reach into a canvas - so the translucent
 * blue bars and the dashed purple line survive in the screenshot exactly as
 * Chart.js drew them. Repainting them in the neutral palette "for
 * consistency" would flatten the one place the design puts colour.
 *
 * Requests/min -> postings per day, P99 latency -> distinct companies per
 * day, still on the left and right axis respectively.
 */

const MONO = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";
const TICK = { color: "#6b7280", font: { family: MONO, size: 10 } };

// Bar and line in one chart: the datasets span two types, so the data object
// is typed over the union while the component is still driven as a bar chart -
// which is how Chart.js models a mixed chart itself.
type Mixed = "bar" | "line";

export function DailyFlowChart({ stats }: { stats: Stats }) {
  const labels = stats.daily.map((point) => fmtDayMonth(point.date));

  const options: ChartOptions<Mixed> = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: "rgba(10,10,10,0.9)",
        titleColor: "#9ca3af",
        bodyColor: "#f3f4f6",
        borderColor: "rgba(255,255,255,0.1)",
        borderWidth: 1,
        padding: 12,
        cornerRadius: 0,
        bodyFont: { family: MONO, size: 12 },
        titleFont: { size: 12, weight: "normal" },
        displayColors: true,
        boxPadding: 4,
        usePointStyle: true,
        callbacks: {
          label: (item) => ` ${item.dataset.label}: ${fmtNumber(item.parsed.y ?? 0)}`,
        },
      },
    },
    scales: {
      x: { grid: { display: false }, border: { display: false }, ticks: { ...TICK, maxRotation: 0 } },
      y: {
        type: "linear",
        position: "left",
        beginAtZero: true,
        grid: { color: "rgba(255,255,255,0.05)" },
        border: { display: false },
        ticks: { ...TICK, maxTicksLimit: 6, precision: 0 },
      },
      y1: {
        type: "linear",
        position: "right",
        beginAtZero: true,
        grid: { display: false },
        border: { display: false },
        ticks: { ...TICK, maxTicksLimit: 6, precision: 0 },
      },
    },
  };

  const data: ChartData<Mixed, number[], string> = {
    labels,
    datasets: [
      {
        label: "Yeni ilan",
        type: "bar",
        data: stats.daily.map((point) => point.count),
        backgroundColor: "rgba(59, 130, 246, 0.15)",
        hoverBackgroundColor: "rgba(59, 130, 246, 0.3)",
        borderColor: "rgba(59, 130, 246, 0.5)",
        borderWidth: 1,
        borderRadius: 2,
        yAxisID: "y",
        order: 2,
      },
      {
        label: "Farklı şirket",
        type: "line",
        data: stats.daily.map((point) => point.companies),
        borderColor: "#a855f7",
        backgroundColor: "transparent",
        borderDash: [4, 4],
        borderWidth: 2,
        pointBackgroundColor: "#0f0f10",
        pointBorderColor: "#a855f7",
        pointBorderWidth: 2,
        // A 90-day series would be a wall of circles; the reference has twelve
        // points and can afford them.
        pointRadius: stats.daily.length > 45 ? 0 : 3,
        pointHoverRadius: 5,
        tension: 0.4,
        yAxisID: "y1",
        order: 1,
      },
    ],
  };

  return <Chart type="bar" options={options as ChartOptions<"bar">} data={data as ChartData<"bar", number[], string>} />;
}
