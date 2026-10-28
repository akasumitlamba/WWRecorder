# Generated UI assets — 2026-10-28

Built-in imagegen was used (no API/CLI fallback). Runtime assets are copied into
this repository; no generated-file absolute path is needed by the application.

## Playback speed

Asset: `app/icons/playback-speed.png`. Source generation prompt:

> Production UI icon for playback SPEED, not playback/play. ONE compact
> speedometer outline: semicircular arch with three short tick marks and a
> diagonal needle pointing upper-right from a small central hub, white #F0F2F5.
> No play triangle. No text at all. Perfectly smooth geometric monoline strokes,
> uniform rounded ends. Professional minimal Windows desktop media tool, legible
> at 18 pixels square. Flat white ink, no texture, no chips, no distressed edges,
> no speckles, no shadows, no glow, no frame, no background, no decorative shapes.
> Icon centered in square canvas with generous transparent padding. Raster asset
> to be reused unchanged beside each speed label.

Transparent outer padding was cropped and the same generated artwork downsampled
for UI use. Native text supplies exact, accessible 0.25×/0.5×/1×/1.5×/2× labels
beside that unchanged symbol. The selected control is 84 logical pixels wide.
Rejected play-triangle artwork is not used.

## Installer welcome art

Asset: `packaging/exe/assets/welcome.png`. Source generation prompt:

> A restrained professional desktop installer sidebar illustration, tall portrait
> 164:314 aspect ratio. Near-black graphite #11151D background, subtle abstract red
> #FF4055 recording-frame corner lines and a delicate red curved ribbon confined
> to the lower third. Upper two thirds calm, flat, empty graphite. Elegant precise
> geometric forms, subtle depth but no glossy effects. No text, no letters, no
> logo, no fake UI, no device, no gradients into light colors. Clean Windows
> desktop application installer artwork; edges of canvas remain graphite, no
> external border.

Inno Setup uses this artwork on its native welcome/finish pages. Options pages
retain native dark controls and canonical small application icon. Existing
startup/shortcut defaults and silent-install behavior are preserved.

## Installer design preview

The generated mockup in local `work/installer-design/installer-design-preview.png`
is a DESIGN PREVIEW, not evidence of a compiled/installed Windows run. Prompt
specified a compact Windows 11 dark native Inno options page with canonical
WWRecorder icon, Additional options heading, two fully visible native checkbox
rows, and native Back/Next/Cancel footer. It explicitly requested an external
'DESIGN PREVIEW — native Windows rendering may differ' caption. Native Windows
layout/font/accent/checkbox rendering still requires verification.
