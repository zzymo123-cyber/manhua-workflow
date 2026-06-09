---
name: Manhua Workflow
description: A restrained production interface for manhua asset, storyboard, and video generation.
colors:
  bg-base: "#ffffff"
  bg-surface: "#f8f9fb"
  bg-elevated: "#ffffff"
  bg-muted: "#f1f3f5"
  text-primary: "#1a1d23"
  text-secondary: "#6b7280"
  text-muted: "#9ca3af"
  accent: "#2563eb"
  accent-hover: "#1d4ed8"
  accent-light: "#eff6ff"
  accent-muted: "#bfdbfe"
  success: "#22c55e"
  warning: "#f59e0b"
  error: "#ef4444"
  border: "#e5e7eb"
typography:
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.4
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.bg-elevated}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
  button-secondary:
    backgroundColor: "{colors.bg-muted}"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
  input:
    backgroundColor: "{colors.bg-surface}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
---

# Design System: Manhua Workflow

## 1. Overview

**Creative North Star: "The Production Desk"**

The interface should feel like a focused workspace for creative production: quiet, structured, and trustworthy. It serves users who need to move many assets through a repeatable pipeline, so hierarchy and state clarity matter more than visual personality.

The system rejects decorative AI SaaS cues: no gradient text, glass effects, oversized floating cards, or playful visual gimmicks. Accent color is rare and functional, used for primary actions, active navigation, and progress communication.

**Key Characteristics:**

- Dense but legible production layout.
- Familiar controls over invented interactions.
- One restrained accent color.
- Explicit task state and recovery language.
- Cross-platform paths and file states treated as product information.

## 2. Colors

The palette is a light neutral product system with one professional blue accent and clear semantic states.

### Primary

- **Production Blue** (`#2563eb`): Primary actions, active navigation, progress fill, and key selection states.

### Neutral

- **Clean White** (`#ffffff`): Main content and elevated surfaces.
- **Panel Mist** (`#f8f9fb`): Header, toolbars, and editing surfaces.
- **Muted Rail** (`#f1f3f5`): Low-emphasis controls, placeholders, and inactive surfaces.
- **Primary Ink** (`#1a1d23`): Body text and user-entered content.
- **Secondary Ink** (`#6b7280`): Labels, metadata, and supporting text.
- **Divider Gray** (`#e5e7eb`): Borders and structural separation.

### Named Rules

**The Functional Accent Rule.** The accent is used only for primary actions, current location, and meaningful state. It is not decoration.

**The No Purple SaaS Rule.** Do not let the accent dominate the page; the product should not read as a generic AI dashboard.

## 3. Typography

**Display Font:** System UI stack
**Body Font:** System UI stack
**Label/Mono Font:** SF Mono / Cascadia Code / Consolas for prompt and template editing only

**Character:** The type system is compact and utilitarian. It favors scanning, stable layout, and repeated use over brand expression.

### Hierarchy

- **Title** (600, 18px, 1.3): Detail panel titles, modal titles, and major tool surfaces.
- **Body** (400, 14px, 1.5): Default UI text, cards, prompts, and messages.
- **Label** (500, 12px, 1.4): Secondary labels, badges, toolbar copy, and metadata.
- **Micro** (400-500, 11px): Dense status indicators and helper text.

### Named Rules

**The Stable Scale Rule.** Product UI uses fixed font sizes, not fluid hero-style type.

## 4. Elevation

The system is mostly flat and uses tonal layers plus borders. Shadows are reserved for overlays, hover affordance, floating assistant surfaces, and modals.

### Shadow Vocabulary

- **Subtle Surface** (`0 1px 2px rgba(0,0,0,0.05)`): Resting asset cards only when a border alone is insufficient.
- **Interactive Lift** (`0 2px 8px rgba(0,0,0,0.08)`): Hover state for clickable cards.
- **Overlay Lift** (`0 4px 16px rgba(0,0,0,0.12)`): Modals and assistant panel.

### Named Rules

**The Flat-By-Default Rule.** Surfaces are flat at rest. Depth appears in response to interaction or overlay context.

## 5. Components

### Buttons

- **Shape:** Compact rectangle with 6px radius.
- **Primary:** Production Blue background with white text.
- **Hover / Focus:** Darken primary background on hover; use visible focus outlines for keyboard users.
- **Secondary:** Muted neutral background with secondary ink. It should not compete with primary actions.

### Status Badges

- **Style:** Small inline pills with icon plus text.
- **State:** Success, warning, error, and needed states must include text or icon, never color alone.

### Cards / Containers

- **Corner Style:** 8px for cards, 12px for modal surfaces.
- **Background:** White or panel mist.
- **Shadow Strategy:** Border first, shadow only for hover or overlays.
- **Border:** Full border only. Avoid colored side stripes.
- **Internal Padding:** 12px for dense cards, 20-24px for larger panels.

### Inputs / Fields

- **Style:** Neutral surface, 1px border, 6-8px radius.
- **Focus:** Border shift plus visible outline or ring.
- **Error / Disabled:** Error state must include a clear message and recovery step.

### Navigation

- **Style:** Compact sidebar with icon and label.
- **Active State:** Full item state using background and text color. Do not use thick side stripes.
- **Mobile Treatment:** Collapse to a horizontal tab strip or drawer; avoid squeezing labels into an unreadable rail.

## 6. Do's and Don'ts

### Do:

- **Do** make every stage show status, blocker, and next action.
- **Do** keep accent color rare and functional.
- **Do** use familiar controls for settings, dialogs, tabs, buttons, and text areas.
- **Do** make errors specific: API key missing, upload failed, polling failed, download failed, or local write failed.
- **Do** verify contrast for muted labels and placeholder text.

### Don't:

- **Don't** look like a generic purple AI SaaS dashboard.
- **Don't** rely on decorative gradients, oversized cards, glass effects, or playful visual gimmicks.
- **Don't** use border-left or border-right greater than 1px as a colored accent.
- **Don't** hide production state behind vague labels such as "processing".
- **Don't** use arbitrary z-index values such as 9999; use a small semantic scale.
- **Don't** make users guess whether a failure came from input parsing, API keys, upload, polling, download, or local file writing.
