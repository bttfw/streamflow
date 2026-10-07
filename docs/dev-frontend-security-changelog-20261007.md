# Frontend security dependency cleanup — development changelog

## 2026-10-07

### Dependency audit

- Replace Tailwind CSS 3.4 with Tailwind CSS 4.3.3 and its dedicated
  `@tailwindcss/postcss` integration. The old dependency chain pulled in
  vulnerable `braces` through `chokidar`, `micromatch`, and `fast-glob`.
- Remove the separate Autoprefixer plugin; Tailwind 4 handles vendor prefixing.
- Upgrade React Router DOM from 6.30 to 7.18.4, covering the reported redirect
  and hydration advisories. Keep the existing browser router and route layout.
- Upgrade `tailwind-merge` to 3.7.0, which supports Tailwind 4 utility names.
- Refresh the transitive `source-map-js` dependency to its patched 1.2.2 version.
- Preserve the existing `tailwindcss-animate` plugin and Radix transition classes.
- Keep the required `npm audit --audit-level=high` workflow unchanged. No audit
  suppression, excluded dependencies, or ignored advisories are introduced.
- Carry forward the existing Werkzeug 3.1.9 and urllib3 2.8.0 security pins into
  both Python lockfiles so this independent branch also passes its backend audit.
  These are the same versions already used by the playback-stability build.

### CSS migration and behavior

- Move the Tailwind configuration into `src/index.css`: existing HSL theme
  variables, custom corner radii, container dimensions, and accordion keyframes.
- Retain the previous sans-serif and monospace font stacks explicitly.
- Migrate deprecated and renamed utility classes, including `shrink-0`,
  `outline-hidden`, `outline-solid`, `shadow-xs`, and `wrap-break-word`.
- Preserve component variant names such as `outline`, monitoring descriptions,
  help content, and historical changelog text. Review the automated migration
  against the source AST so utility rewrites do not alter application data.
- Preserve the existing channel/checker/preflight behavior and stored settings.
- Tailwind 4 requires modern browsers: Safari 16.4+, Chrome 111+, Firefox 128+.
  See the [official upgrade guide](https://tailwindcss.com/docs/upgrade-guide).

### Validation

- Clean `npm ci` installation succeeds; frontend audit reports zero findings.
- All 287 existing frontend tests on the independent `dev` branch pass.
- Production frontend build succeeds.
- Browser comparison covers the real Help page in Light and Dark themes,
  including element geometry, typography, theme colors, and screenshots.
- Additional route, control, mobile, and combined Unraid validation is in progress.

### Scope

This branch starts directly from upstream `dev`; it does not include the pending
efficiency/theme or playback-stability feature commits. Live verification uses a
separate combined validation build so the currently installed features remain
available while testing the dependency cleanup.
