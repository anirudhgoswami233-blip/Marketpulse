"use client";

import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { INTRADAY_RANGES, SMA_OVERLAYS, sma, toCandlePoints, toChartPoints, toVolumePoints } from "@/lib/chart";
import { chartThemeOptions, lineSeriesOptions, tokenColor } from "@/lib/chartTheme";
import { formatCompact, formatPrice } from "@/lib/format";
import { subscribeTheme } from "@/lib/theme";
import type { Chart } from "@/types/api";

export type ChartMode = "line" | "candles";

interface Hover {
  label: string;
  close: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
}

const time = (seconds: number) => seconds as UTCTimestamp;

/** The chart itself. Loaded on demand by PriceChart so the charting library stays out of the page bundle. */
export default function ChartCanvas({
  chart,
  currency,
  mode = "line",
  overlays = [],
  showVolume = false,
}: {
  chart: Chart;
  currency: string | null;
  mode?: ChartMode;
  /** SMA periods to draw (see SMA_OVERLAYS). */
  overlays?: number[];
  showVolume?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const intraday = INTRADAY_RANGES.has(chart.range);
  const overlayKey = overlays.join(",");

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const theme = () => {
      const base = chartThemeOptions();
      return { ...base, timeScale: { ...base.timeScale, timeVisible: intraday, secondsVisible: false } };
    };
    const instance: IChartApi = createChart(container, {
      ...theme(),
      autoSize: true,
      height: 288,
      handleScroll: false,
      handleScale: false,
    });

    const closes = toChartPoints(chart.bars, chart.range, chart.timezone);
    const candles = toCandlePoints(chart.bars, chart.range, chart.timezone);
    const volumes = showVolume ? toVolumePoints(chart.bars, chart.range, chart.timezone) : [];
    const candleColors = () => {
      const up = tokenColor("--up");
      const down = tokenColor("--down");
      return { upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down };
    };

    let price: ISeriesApi<"Line"> | ISeriesApi<"Candlestick">;
    if (mode === "candles") {
      const series = instance.addSeries(CandlestickSeries, { ...candleColors(), priceLineVisible: false });
      series.setData(candles.map((c) => ({ ...c, time: time(c.time) })));
      price = series;
    } else {
      const series = instance.addSeries(LineSeries, { ...lineSeriesOptions(), lastValueVisible: true });
      series.setData(closes.map((p) => ({ time: time(p.time), value: p.value })));
      price = series;
    }

    // Moving averages share the price axis; each keeps its own colour from the validated series palette.
    const averages = SMA_OVERLAYS.filter((o) => overlayKey.split(",").includes(String(o.period))).map((overlay) => {
      const series = instance.addSeries(LineSeries, {
        color: tokenColor(overlay.token),
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      series.setData(sma(closes, overlay.period).map((p) => ({ time: time(p.time), value: p.value })));
      return { overlay, series };
    });

    // Volume sits in the bottom fifth on its own scale so it never distorts the price axis.
    let volume: ISeriesApi<"Histogram"> | null = null;
    const volumeData = () =>
      volumes.map((v) => ({ time: time(v.time), value: v.value, color: tokenColor(v.up ? "--up-flash" : "--down-flash") }));
    if (volumes.length > 0) {
      volume = instance.addSeries(HistogramSeries, {
        priceScaleId: "",
        priceFormat: { type: "volume" },
        priceLineVisible: false,
        lastValueVisible: false,
      });
      volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      volume.setData(volumeData());
    }
    instance.timeScale().fitContent();

    const volumeByTime = new Map(volumes.map((v) => [v.time, v.value]));
    const candleByTime = new Map(candles.map((c) => [c.time, c]));
    instance.subscribeCrosshairMove((param) => {
      const point = param.seriesData.get(price);
      if (!param.time || !point) {
        setHover(null);
        return;
      }
      const seconds = Number(param.time);
      const date = new Date(seconds * 1000);
      const label = intraday ? date.toISOString().slice(0, 16).replace("T", " ") : date.toISOString().slice(0, 10);
      const candle = candleByTime.get(seconds);
      const close = "value" in point ? point.value : "close" in point ? point.close : null;
      if (close === null) {
        setHover(null);
        return;
      }
      setHover({
        label,
        close,
        ...(mode === "candles" && candle ? { open: candle.open, high: candle.high, low: candle.low } : {}),
        volume: volumeByTime.get(seconds),
      });
    });

    // Restyle when the user toggles the theme or the OS switches between light and dark.
    const unsubscribeTheme = subscribeTheme(() => {
      instance.applyOptions(theme());
      if (mode === "candles") price.applyOptions(candleColors());
      else price.applyOptions(lineSeriesOptions());
      for (const { overlay, series } of averages) series.applyOptions({ color: tokenColor(overlay.token) });
      volume?.setData(volumeData());
    });

    return () => {
      unsubscribeTheme();
      instance.remove();
    };
  }, [chart, intraday, mode, overlayKey, showVolume]);

  const recent = chart.bars.slice(-30).reverse();
  const money = (value: number) => formatPrice(value, currency);
  return (
    <div>
      <p className="tabular h-5 truncate text-xs text-secondary" aria-live="polite">
        {hover ? (
          <>
            {hover.label}
            {intraday && chart.timezone ? ` (${chart.timezone})` : ""} ·{" "}
            {hover.open !== undefined && hover.high !== undefined && hover.low !== undefined
              ? `O ${money(hover.open)} · H ${money(hover.high)} · L ${money(hover.low)} · C ${money(hover.close)}`
              : money(hover.close)}
            {hover.volume !== undefined && ` · Vol ${formatCompact(hover.volume)}`}
          </>
        ) : (
          <span className="text-muted">Hover the chart for prices</span>
        )}
      </p>
      <div ref={containerRef} className="h-72 w-full" data-testid="price-chart" />
      <details className="mt-2 text-xs text-secondary">
        <summary className="cursor-pointer">Show data table</summary>
        <div className="overflow-x-auto">
          <table className="data-table mt-2 max-w-xl">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col" className="num">
                  Open
                </th>
                <th scope="col" className="num">
                  High
                </th>
                <th scope="col" className="num">
                  Low
                </th>
                <th scope="col" className="num">
                  Close
                </th>
                <th scope="col" className="num">
                  Volume
                </th>
              </tr>
            </thead>
            <tbody>
              {recent.map((bar) => (
                <tr key={bar.timestamp}>
                  <td className="whitespace-nowrap">
                    {intraday ? bar.timestamp.slice(0, 16).replace("T", " ") + " UTC" : bar.timestamp.slice(0, 10)}
                  </td>
                  <td className="num">{formatPrice(bar.open, currency)}</td>
                  <td className="num">{formatPrice(bar.high, currency)}</td>
                  <td className="num">{formatPrice(bar.low, currency)}</td>
                  <td className="num">{formatPrice(bar.close, currency)}</td>
                  <td className="num">{bar.volume === null ? "—" : formatCompact(bar.volume)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
