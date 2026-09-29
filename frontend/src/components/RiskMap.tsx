import { useEffect, useMemo, useRef } from "react";
import { GeoJSON, MapContainer, useMap } from "react-leaflet";
import L from "leaflet";
import type { DistrictFeature, DistrictsResponse } from "../api/types";
import { HAZARD_LABEL, pct, SEVERITY_STYLE } from "../lib/format";

const TN_BOUNDS = L.latLngBounds([7.9, 76.1], [13.6, 80.4]);

function styleFor(f: DistrictFeature, dark: boolean): L.PathOptions {
  const r = f.properties.risk;
  const s = SEVERITY_STYLE[r.severity];
  const p = r.top_probability ?? 0;
  return {
    fillColor: s.fill,
    // Stronger fill for more likely hazards; calm districts stay neutral.
    fillOpacity: r.severity === "none" ? (dark ? 0.12 : 0.35) : 0.35 + 0.5 * Math.min(1, p),
    color: dark ? "#3f3f46" : "#ffffff",
    weight: 1,
  };
}

function tooltipHtml(f: DistrictFeature): string {
  const r = f.properties.risk;
  const sev = SEVERITY_STYLE[r.severity];
  const hz = r.top_hazard
    ? `${HAZARD_LABEL[r.top_hazard]} · ${pct(r.top_probability)}`
    : "No hazards detected";
  const others = r.hazard_types.filter((t) => t !== r.top_hazard).map((t) => HAZARD_LABEL[t]);
  return `<div style="min-width:150px">
    <div style="font-weight:600;font-size:13px">${f.properties.name}</div>
    <div style="display:flex;align-items:center;gap:6px;margin-top:4px">
      <span style="width:8px;height:8px;border-radius:9px;background:${sev.fill}"></span>${sev.label}</div>
    <div style="margin-top:2px;opacity:.8">${hz}</div>
    ${others.length ? `<div style="margin-top:2px;opacity:.6">Also: ${others.join(", ")}</div>` : ""}
    <div style="margin-top:6px;opacity:.5">Click for district detail</div></div>`;
}

function FitBounds() {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(TN_BOUNDS, { padding: [8, 8] });
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(map.getContainer());
    return () => ro.disconnect();
  }, [map]);
  return null;
}

/**
 * District risk choropleth. Polygons are created once; when the date (and so the risk)
 * changes, each layer's style is updated in place so the CSS fill transition tweens colours.
 */
export function RiskMap({ data, onSelect, dark, selected }: {
  data: DistrictsResponse;
  onSelect: (slug: string) => void;
  dark: boolean;
  selected?: string;
}) {
  const layers = useRef(new Map<number, L.Path>());
  const byId = useMemo(() => new Map(data.features.map((f) => [f.id, f])), [data]);
  // Geometry never changes; keep the first collection for the GeoJSON layer.
  const geometry = useRef(data);

  useEffect(() => {
    layers.current.forEach((layer, id) => {
      const f = byId.get(id);
      if (!f) return;
      layer.setStyle({ ...styleFor(f, dark), weight: f.properties.slug === selected ? 2.5 : 1,
        ...(f.properties.slug === selected ? { color: dark ? "#e4e4e7" : "#14532d" } : {}) });
      layer.setTooltipContent(tooltipHtml(f));
    });
  }, [byId, dark, selected]);

  return (
    <MapContainer bounds={TN_BOUNDS} zoomControl={false} attributionControl={false} scrollWheelZoom={false}
      className="h-full w-full" style={{ background: "transparent" }} minZoom={6} maxZoom={9} zoomSnap={0.25}>
      <FitBounds />
      <GeoJSON
        data={geometry.current as unknown as GeoJSON.FeatureCollection}
        style={(f) => styleFor(byId.get((f as unknown as DistrictFeature).id) ?? (f as unknown as DistrictFeature), dark)}
        onEachFeature={(feature, layer) => {
          const f = feature as unknown as DistrictFeature;
          const path = layer as L.Path;
          layers.current.set(f.id, path);
          path.bindTooltip(tooltipHtml(byId.get(f.id) ?? f), { sticky: true, className: "av-tip", direction: "top", offset: [0, -8] });
          path.on({
            mouseover: () => path.setStyle({ weight: 2.5 }),
            mouseout: () => path.setStyle({ weight: 1 }),
            click: () => onSelect(f.properties.slug),
          });
        }}
      />
    </MapContainer>
  );
}

export function MapLegend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-[12px] text-muted">
      {(["warning", "watch", "info", "none"] as const).map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SEVERITY_STYLE[s].fill }} />
          {SEVERITY_STYLE[s].label}
        </span>
      ))}
      <span className="text-faint">· darker = more likely</span>
    </div>
  );
}
