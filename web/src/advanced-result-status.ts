// A qualified, unsaved calculation is not a transport failure. Keep the API's
// machine status in provenance, but give the person an actionable explanation.
const explanations: Record<string, string> = {
  no_active_natal: 'Create a current natal chart for this person, then try again.',
  unsupported_stale_birth_source: 'The saved birth details have changed. Open this person’s profile and update the current natal chart before trying again.',
  unsupported_uncertain_birth_time: 'An exact birth time is needed. Open this person’s profile to supply or correct it before trying again.',
  unsupported_uncertain_birth_time_or_non_natal_chart: 'This chart cannot support this calculation. Open the person’s profile and supply an exact birth time for a current natal chart.',
  unsupported_natal_mc_houses: 'This chart has no supported natal MC or houses. Check the birth time and place in the person’s profile.',
  unsupported_natal_angle: 'This natal angle is unavailable. Check the birth time and place in the person’s profile or choose a planetary contact.',
  unsupported_missing_source_coordinates: 'The saved birth coordinates are unavailable. Check both people’s birthplaces and generate current charts before trying again.',
  unsupported_incompatible_house_or_node_profiles: 'These charts use incompatible house or node settings. Generate compatible current natal charts before comparing them.',
};

export function unavailableCalculation(technique: string, status: string): string {
  return `${technique} was not saved. ${explanations[status] ||
    'This calculation is not available for the selected charts. Check their current birth details or try another calculation.'}`;
}
