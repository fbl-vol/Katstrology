import { useEffect, useState } from 'react';
import { api, type Workspace } from './api';
import type { Chart } from './natal';

type Place = { id: string; name: string; region: string; country: string;
  latitude: number; longitude: number };
export type ReferenceChoice = {
  kind: 'birthplace' | 'city' | 'coordinates' | 'missing';
  latitude: string; longitude: string; placeId: string | null; label: string | null;
};

export function birthReference(chart: Chart | null): ReferenceChoice {
  const latitude = chart?.result.birth.latitude;
  const longitude = chart?.result.birth.longitude;
  return { kind: latitude == null || longitude == null ? 'missing' : 'birthplace',
    latitude: latitude == null ? '' : String(latitude),
    longitude: longitude == null ? '' : String(longitude), placeId: null, label: null };
}

const placeLabel = (place: Place) => [place.name, place.region, place.country].filter(Boolean).join(', ');

export function ReturnReferencePlace({ workspace, value, onChange }: {
  workspace: Workspace; value: ReferenceChoice; onChange: (value: ReferenceChoice) => void;
}) {
  const [editing, setEditing] = useState(value.kind === 'missing');
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState<Place[]>([]);
  const [searchError, setSearchError] = useState(false);

  useEffect(() => {
    if (value.kind === 'missing') setEditing(true);
    if (value.kind !== 'missing') setEditing(false);
  }, [value.kind]);
  useEffect(() => {
    if (!editing || query.trim().length < 2) { setMatches([]); return; }
    let current = true;
    const timer = window.setTimeout(() => {
      void api<{ places: Place[] }>('places/search', workspace.csrf, 'POST', { query: query.trim() })
        .then(found => { if (current) { setMatches(found.places); setSearchError(false); } })
        .catch(() => { if (current) { setMatches([]); setSearchError(true); } });
    }, 180);
    return () => { current = false; window.clearTimeout(timer); };
  }, [editing, query, workspace.csrf]);

  return <fieldset className="return-reference"><legend>Reference place</legend>
    {value.kind === 'birthplace' && <p><strong>Birthplace</strong> · saved coordinates ({value.latitude}°, {value.longitude}°)</p>}
    {value.kind === 'city' && <p><strong>{value.label}</strong> · offline city-centre reference ({value.latitude}°, {value.longitude}°)</p>}
    {value.kind === 'coordinates' && <p><strong>Custom coordinates</strong> · specify both values for this return chart.</p>}
    {value.kind === 'missing' && <p role="status">Saved birthplace coordinates are unavailable. Choose a city or enter both coordinates; no location is assumed.</p>}
    {!editing && <button type="button" onClick={() => setEditing(true)}>Change place</button>}
    {editing && <div className="return-reference-choices">
      {value.kind !== 'missing' && <p>The current place remains selected until you choose a replacement.</p>}
      <label>Find a city or town<input autoComplete="off" value={query} placeholder="Search city, then choose region and country"
        onChange={event => { setQuery(event.target.value); setSearchError(false); }} /></label>
      {matches.length > 0 && <div role="group" aria-label="Offline reference places" className="place-results">
        {matches.map(place => <button type="button" key={place.id} onClick={() => {
          onChange({ kind: 'city', latitude: String(place.latitude), longitude: String(place.longitude),
            placeId: place.id, label: placeLabel(place) });
          setMatches([]); setQuery(''); setEditing(false);
        }}>{placeLabel(place)} <small>GeoNames city-centre reference</small></button>)}
      </div>}
      {searchError && <p role="alert">Local city suggestions are unavailable. Enter coordinates manually or try again.</p>}
      <button type="button" onClick={() => {
        onChange({ ...value, kind: 'coordinates', placeId: null, label: null }); setEditing(false);
      }}>Enter precise coordinates</button>
      {value.kind !== 'missing' && <button type="button" onClick={() => setEditing(false)}>Keep current place</button>}
    </div>}
    {value.kind === 'coordinates' && !editing && <div className="return-reference-coordinates">
      <label>Latitude<input aria-label="Latitude" required type="number" min="-90" max="90" step="any"
        value={value.latitude} onChange={event => onChange({ ...value, latitude: event.target.value })} /></label>
      <label>Longitude<input aria-label="Longitude" required type="number" min="-180" max="180" step="any"
        value={value.longitude} onChange={event => onChange({ ...value, longitude: event.target.value })} /></label>
    </div>}
    <p>Changing this place changes houses and angles, not the geocentric return moment. City centres are references, not verified birth addresses.</p>
  </fieldset>;
}
