export const colors = {
  bg: '#0a1420',
  bgEdge: '#122032',
  panel: '#0f1d2e',
  panel2: '#0c1826',
  panelEdge: '#233a52',
  line: 'rgba(174, 210, 245, 0.12)',
  text: '#f3f8fd',
  textDim: '#c7d7e6',
  secondary: '#8ba0b5',
  muted: '#7e93a7',
  blue: '#4fa8dc',
  teal: '#45c2b8',
  tealDark: '#052821',
  orange: '#ff9a3d',
  danger: '#ff8a7a',
  success: '#6fe0b8',
  warning: '#ffcf6b',
};

export const DISPOSITION_META = {
  interested: { label: 'Interested', color: colors.success, bg: 'rgba(111, 224, 184, 0.12)' },
  follow_up: { label: 'Follow-up', color: colors.blue, bg: 'rgba(79, 168, 220, 0.12)' },
  no_decision: { label: 'No decision', color: colors.secondary, bg: 'rgba(139, 160, 181, 0.12)' },
  not_interested: { label: 'Not interested', color: colors.danger, bg: 'rgba(255, 138, 122, 0.12)' },
  do_not_contact: { label: 'Do not contact', color: colors.danger, bg: 'rgba(255, 138, 122, 0.16)' },
};
