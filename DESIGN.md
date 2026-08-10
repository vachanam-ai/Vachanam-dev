# Vachanam Design System

## Visual Theme

Vachanam uses a "living clinic" visual language: clear clinical surfaces, peacock-teal structure, deep botanical ink, and small marigold and coral signals. Public pages are expressive and image-led. Authenticated product pages are restrained, fast, and information-led.

## Color Palette

- `canvas`: cool mineral white for the page ground.
- `surface`: clean white or deep botanical surface in dark mode.
- `ink`: deep green-black for primary text.
- `muted`: slate-teal for supporting text.
- `primary`: peacock teal for primary actions and selection.
- `primary-strong`: deep teal for navigation and high-emphasis regions.
- `highlight`: fresh mint for selected and informational surfaces.
- `marigold`: warm attention and waiting states.
- `coral`: urgent and destructive states.
- `indigo`: secondary data series and informational contrast.

All colors are semantic CSS variables. Product components do not hardcode palette values.

## Typography

- General Sans is self-hosted and carries all product UI roles.
- Pacifico is limited to the Vachanam wordmark.
- Public display type uses General Sans with strong weight and controlled tracking rather than a generic editorial serif.
- Product headings use a compact fixed scale. Marketing headings may use fluid `clamp()` values capped at 88px.
- Numbers use tabular figures.

## Shape and Depth

- Product controls: 10-12px radius.
- Product cards and panels: 14-16px radius.
- Marketing media frames: up to 24px radius when the image is the composition.
- Buttons may be pill-shaped only for primary calls to action.
- Borders or restrained short shadows create separation, never both as decoration.

## Layout

- Product shell: dark teal navigation rail, light task canvas, sticky contextual header, and responsive mobile drawer.
- Marketing: asymmetric split hero, proof strip, sticky workflow story, varied feature composition, comparison-led pricing, and a compact conversion form.
- Product page content max width is 1240px. Prose max width is 72ch.
- Mobile layouts collapse to a strict single column with 16px gutters.

## Components

- Buttons expose default, hover, focus, pressed, disabled, and loading states.
- Inputs always have visible labels, 44px minimum height, inline errors, and a strong focus ring.
- Cards group one task or one metric. Nested cards are avoided.
- Status tags pair color with text or an icon.
- Empty and loading states explain what happens next.
- Navigation uses Phosphor icons with one consistent stroke weight.

## Motion

- Product interactions: 150-250ms, transform and opacity only, with strong ease-out curves.
- Button press feedback scales to 0.97 without moving layout.
- Marketing hero and story sequences use scoped GSAP timelines and ScrollTrigger.
- Every GSAP animation uses React-safe cleanup and respects `prefers-reduced-motion`.
- No global scroll listeners, layout-property animation, or perpetual decoration.

## Content

- Write direct, grounded statements. Avoid buzzwords, fake precision, and medical claims.
- Button labels describe the resulting action.
- Never expose patient health information in decorative examples.
- Use normal punctuation in marketing copy and avoid em dashes.

## Page Overrides

### Landing and public help

Use the committed brand palette, editorial clinic photography, asymmetric compositions, and purposeful scroll storytelling.

### Auth and onboarding

Use a focused split layout with clear progress, visible labels, recovery states, and no distracting ambient animation.

### Dashboard and operations

Use restrained color, dense but breathable task panels, persistent navigation, consistent charts, skeleton loading, and immediate state feedback.
