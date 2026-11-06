export const signs = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
  'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces'];

export function zodiac(degrees: number) {
  const within = degrees % 30;
  return `${Math.floor(within)}°${String(Math.floor((within % 1) * 60)).padStart(2, '0')}′ ${signs[Math.floor(degrees / 30)]}`;
}

export function point(degrees: number, ascendant: number, radius: number) {
  const radians = Math.PI + (ascendant - degrees) * Math.PI / 180;
  return { x: 240 + radius * Math.cos(radians), y: 240 + radius * Math.sin(radians) };
}
