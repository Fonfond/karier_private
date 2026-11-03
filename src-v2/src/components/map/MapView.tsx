import { useEffect } from 'react'
import L from 'leaflet'
import { CircleMarker, ImageOverlay, MapContainer, Marker, Polyline, useMap, useMapEvents } from 'react-leaflet'
import type { AssetBrief, MapLayer } from '../../lib/gis'
import { STATUS_COLOR } from '../../lib/gis'

interface MapViewProps {
  layer: MapLayer
  assets: AssetBrief[]
  selectedId: string | null
  onSelect: (id: string) => void
  adding: boolean
  onMapClick: (x: number, y: number) => void
  draft: { x: number; y: number } | null
  history?: Array<{ x: number; y: number }>
}

function markerIcon(asset: AssetBrief, selected: boolean): L.DivIcon {
  const color = asset.type.color ?? '#4C9AFF'
  const status = STATUS_COLOR[asset.status] ?? '#6B7A8A'
  const size = selected ? 44 : 36
  return L.divIcon({
    className: 'karier-marker',
    html: `
      <span class="karier-marker__body" style="--c:${color};--ring:${status};--s:${size}px">
        <span class="karier-marker__icon">${asset.type.icon ?? '●'}</span>
      </span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

const draftIcon = L.divIcon({
  className: 'karier-marker karier-marker--draft',
  html: '<span class="karier-marker__body" style="--c:#4C9AFF;--ring:#fff;--s:38px"><span class="karier-marker__icon">＋</span></span>',
  iconSize: [38, 38],
  iconAnchor: [19, 19],
})

function ClickCatcher({ enabled, onClick }: { enabled: boolean; onClick: (x: number, y: number) => void }) {
  useMapEvents({
    click(event) {
      if (!enabled) return
      onClick(event.latlng.lng, event.latlng.lat)
    },
  })
  return null
}

function FitBounds({ bounds }: { bounds: L.LatLngBounds }) {
  const map = useMap()
  useEffect(() => {
    const resize = () => map.invalidateSize()

    // «Заполнить экран», а не «вписать целиком»: на вертикальном телефоне
    // картинка 16:9 иначе превращается в узкую полоску по центру.
    const cover = () => {
      const size = map.getSize()
      const width = bounds.getEast() - bounds.getWest()
      const height = bounds.getNorth() - bounds.getSouth()
      if (!width || !height || !size.x || !size.y) return
      const zoom = Math.max(Math.log2(size.x / width), Math.log2(size.y / height))
      const clamped = Math.min(Math.max(zoom, map.getMinZoom()), map.getMaxZoom())
      map.setView(bounds.getCenter(), clamped, { animate: false })
    }

    const raf = requestAnimationFrame(() => {
      resize()
      cover()
    })
    window.addEventListener('resize', resize)
    window.addEventListener('orientationchange', resize)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      window.removeEventListener('orientationchange', resize)
    }
  }, [map, bounds])
  return null
}

export function MapView({
  layer,
  assets,
  selectedId,
  onSelect,
  adding,
  onMapClick,
  draft,
  history,
}: MapViewProps) {
  const bounds = L.latLngBounds(
    [layer.bounds[0][0], layer.bounds[0][1]],
    [layer.bounds[1][0], layer.bounds[1][1]],
  )
  const historyPoints: Array<[number, number]> = (history ?? []).map((point) => [point.y, point.x])

  return (
    <MapContainer
      crs={L.CRS.Simple}
      bounds={bounds}
      minZoom={layer.min_zoom}
      maxZoom={layer.max_zoom}
      zoomSnap={0.25}
      zoomDelta={0.5}
      maxBounds={bounds.pad(0.25)}
      maxBoundsViscosity={0.9}
      attributionControl={false}
      zoomControl={false}
      className="h-full w-full bg-[#070C10]"
    >
      <ImageOverlay url={layer.image_url} bounds={bounds} className="karier-layer" />
      <FitBounds bounds={bounds} />
      <ClickCatcher enabled={adding} onClick={onMapClick} />

      {assets.map((asset) =>
        asset.x === null || asset.y === null ? null : (
          <Marker
            key={asset.id}
            position={[asset.y, asset.x]}
            icon={markerIcon(asset, asset.id === selectedId)}
            eventHandlers={{ click: () => onSelect(asset.id) }}
            zIndexOffset={asset.id === selectedId ? 1000 : 0}
          />
        ),
      )}

      {historyPoints.length > 1 ? (
        <>
          <Polyline positions={historyPoints} pathOptions={{ color: '#F5A524', weight: 2, dashArray: '6 6' }} />
          {historyPoints.map((point, index) => (
            <CircleMarker
              key={`move-${index}`}
              center={point}
              radius={4}
              pathOptions={{ color: '#F5A524', fillColor: '#F5A524', fillOpacity: 0.6, weight: 1 }}
            />
          ))}
        </>
      ) : null}

      {draft ? <Marker position={[draft.y, draft.x]} icon={draftIcon} interactive={false} /> : null}
    </MapContainer>
  )
}
