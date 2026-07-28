---
name: Vivid Ink
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#393939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1c1b1b'
  surface-container: '#201f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353534'
  on-surface: '#e5e2e1'
  on-surface-variant: '#c7c4d7'
  inverse-surface: '#e5e2e1'
  inverse-on-surface: '#313030'
  outline: '#908fa0'
  outline-variant: '#464554'
  surface-tint: '#c0c1ff'
  primary: '#c0c1ff'
  on-primary: '#1000a9'
  primary-container: '#8083ff'
  on-primary-container: '#0d0096'
  inverse-primary: '#494bd6'
  secondary: '#4fdbc8'
  on-secondary: '#003731'
  secondary-container: '#04b4a2'
  on-secondary-container: '#003f38'
  tertiary: '#ffb2b7'
  on-tertiary: '#67001b'
  tertiary-container: '#ff516a'
  on-tertiary-container: '#5b0017'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e1e0ff'
  primary-fixed-dim: '#c0c1ff'
  on-primary-fixed: '#07006c'
  on-primary-fixed-variant: '#2f2ebe'
  secondary-fixed: '#71f8e4'
  secondary-fixed-dim: '#4fdbc8'
  on-secondary-fixed: '#00201c'
  on-secondary-fixed-variant: '#005048'
  tertiary-fixed: '#ffdadb'
  tertiary-fixed-dim: '#ffb2b7'
  on-tertiary-fixed: '#40000d'
  on-tertiary-fixed-variant: '#92002a'
  background: '#131313'
  on-background: '#e5e2e1'
  surface-variant: '#353534'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 57px
    fontWeight: '700'
    lineHeight: 64px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
  title-lg:
    fontFamily: Inter
    fontSize: 22px
    fontWeight: '500'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: 0.5px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0.25px
  label-lg:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.1px
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.5px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  gutter: 16px
  margin-mobile: 16px
  margin-tablet: 24px
---

## Brand & Style
The design system focuses on a high-fidelity, cinematic reading experience tailored for comic book enthusiasts. The brand personality is immersive and premium, prioritizing content-first layouts that disappear to let the artwork shine. 

The design style is **Modern Corporate with a High-Contrast edge**, specifically optimized for AMOLED displays. It leverages the Material Design 3 (M3) framework but enhances it with deeper blacks and vibrant, electric accents. The emotional response should be one of "digital luxury"—smooth transitions, deep ink-like backgrounds, and sharp, accessible typography that feels like a modern gallery.

## Colors
The color palette is anchored by "Inky Midnight" (AMOLED Black) to save battery and provide infinite contrast for comic panels. 

- **Primary Indigo (#6366F1):** Used for key actions, active states, and branding elements. It provides a modern, energetic feel without being fatiguing.
- **Secondary Teal (#14B8A6):** Used for success states, download indicators, and secondary categorizations.
- **Tertiary Rose (#F43F5E):** Reserved for alerts, favorites, or high-urgency notifications.
- **Surface Strategy:** In Dark Mode, the absolute background is `#000000`. Overlays and cards use `#121212` or `#1E1E1E` with subtle primary-tinted overlays (2-5% opacity) to maintain M3 depth logic.
- **Light Mode Variant:** Swaps the background to a clean `#FAFAFA` with surfaces at `#FFFFFF`. Primary and Secondary colors retain their hex values but are adjusted for AA/AAA contrast ratios against white.

## Typography
The system utilizes **Inter** across all levels for its exceptional legibility and modern, neutral aesthetic. 

- **Headlines:** Use Semi-Bold (600) or Bold (700) weights with tighter letter spacing to create a strong visual anchor for series titles.
- **Body:** Standardized on a 16px base for long-form synopsis reading. Line heights are generous (1.5x) to ensure comfort during extended sessions.
- **Scale:** On mobile devices, Display and Large Headline sizes scale down by 15% to prevent awkward text wrapping, while keeping the optical weight consistent.
- **Labels:** Used for metadata (Issue numbers, file sizes, timestamps). These leverage Medium (500) weights to remain distinct from body text even at smaller scales.

## Layout & Spacing
This design system adheres to a strict **8dp base grid**. All measurements for padding, height, and alignment must be multiples of 8 (or 4 for micro-adjustments).

- **Grid Model:** A 4-column fluid grid is used for mobile, expanding to 8 columns for tablets and 12 for desktop/web views.
- **Margins:** Standard 16dp side margins for mobile to maximize content real estate. On tablets, margins increase to 24dp or 32dp to prevent lines of text from becoming too wide.
- **Content Density:** High-density grids are preferred for the "Library" view (3 columns of covers), while low-density "Editorial" spacing is used for discovery and individual comic detail pages.

## Elevation & Depth
Elevation is expressed through **Tonal Layers** rather than heavy drop shadows. In the AMOLED dark mode, depth is critical to distinguish between the background and interactive elements.

- **Level 0 (Background):** Pure `#000000`.
- **Level 1 (Cards/Sheets):** `#121212` with a 0.5px subtle border (Primary at 10% opacity) to define edges.
- **Level 2 (Dialogs/Menus):** `#1E1E1E` with a soft ambient shadow (Blur: 12px, Y: 4px, Color: Black at 40% opacity).
- **Glassmorphism:** Bottom Navigation Bars and Top App Bars utilize a backdrop blur (20px) with a semi-transparent surface (`#121212` at 80% alpha) to provide context of the content scrolling underneath.

## Shapes
The shape language is friendly but structured, utilizing large radii to soften the high-contrast color palette.

- **Containers & Cards:** Use a **24dp (rounded-xl)** corner radius. This applies to comic cover cards, featured banners, and modal sheets.
- **Inputs & Buttons:** Use a **16dp (rounded-lg)** radius. This creates a distinct visual hierarchy between "containers" and "interactive elements."
- **FABs & Selection Indicators:** Use **Full Circular (Pill)** rounding to emphasize their priority and Material 3 heritage.

## Components
Consistent component styling ensures the app feels cohesive across all states.

- **Buttons:** Primary buttons are filled with Indigo (#6366F1) and use 16dp corners. Text is White. Outlined buttons use a 1px border of the primary color.
- **Floating Action Buttons (FAB):** Follow M3 specs. Large FAB for "Start Reading" or "Download All," using the Primary color. Small FABs for secondary actions like "Add to Collection."
- **Cards:** 24dp rounding. Use an aspect ratio of 2:3 for comic covers. Include a subtle 1px inner stroke in dark mode to prevent the card from bleeding into the AMOLED black background.
- **Inputs:** 16dp rounding. Filled style with a bottom indicator line or a full subtle outline. Focus states must use the Secondary Teal (#14B8A6).
- **Bottom Navigation:** Uses the M3 pill-shaped active indicator. The container uses a backdrop-blur effect.
- **Chips:** For genres or tags. 8dp rounding. Low-contrast background (Primary at 15% opacity) with Primary colored text.
- **Icons:** Use **Material Symbols (Outlined)**. Stroke weight should be set to 200 (Thin) or 400 (Regular) to maintain the premium, clean aesthetic.