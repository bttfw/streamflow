# Matrix appearance

Additional color-only appearance based on black/charcoal surfaces and green
accents. Layout, typography, spacing, corner radius and operational behavior
retain the existing values.

## Palette

| Use | Color |
| --- | --- |
| Page background | `#000000` |
| Cards and sidebar | `#0c0c0c` |
| Popovers | `#101010` |
| Primary, progress and focus | `#16a34a` |
| Text on primary surfaces | `#000000` |
| Main text | `#fafafa` |
| Secondary text | `#a6a6a6` |
| Secondary surfaces | `#1a1a1a` |
| Borders | `#242424` |
| Input borders | `#2e2e2e` |

Dark text on the green primary surfaces provides approximately 6.38:1
contrast at full opacity. Main and secondary text on cards provide
approximately 18.73:1 and 8.01:1 respectively. These are palette calculations,
not a rendered UI accessibility audit.

Green accents belong to navigation, primary actions, progress and focus.
Warnings, errors, information and provider states keep their semantic colors.

## Integration

- Visible entry: sidebar `Appearance` theme menu -> `Matrix`.
- Stored value: existing `localStorage.theme` key with value `matrix`.
- Effective mode: `dark`; root classes: `dark matrix` so existing dark variants
  continue to apply. Matrix does not follow the system appearance.
- Returning to Light, Dark or Auto removes `matrix`. Auto continues to follow
  the system preference using the existing listener and cleanup.
- Existing CSS custom properties carry the palette. Theme-specific rules
  remove the blue body gradient and color the selected sidebar navigation
  item without changing its structure.
- No new packages, backend endpoints or server settings are required.

## Validation - 2026-10-03

All 295 existing frontend tests passed across 39 files, and the production
frontend build passed. Browser validation of that build, using read-only live
API data, passed 47 checks with no page exceptions or backend mutation requests.
It covered all pairs of appearance selections, reload persistence, Auto system
changes, Matrix isolation from system changes, keyboard menu closure, computed
palette/selected navigation colors, unchanged layout axes, four pages and mobile
navigation/theme switching.

The image build, native Unraid DockerMan deployment and repeated live browser
validation are pending. Screenshots will document the deployed UI with IP text
masked; they are review artifacts outside the application image.
