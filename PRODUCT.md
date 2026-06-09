# Product

## Register

product

## Users

This product is for the project owner, their collaborators, and creative production roles involved in manhua or short-drama asset generation: writers, directors, editors, visual artists, operators, and non-technical teammates who need to move a story package through prompt, image, storyboard, and video production.

Users are usually in a production workflow, not browsing for inspiration. They need to inspect project readiness, identify blocked steps, batch-generate assets, recover from failures, and understand what the system is doing without reading code or logs.

## Product Purpose

Manhua Workflow turns a structured script input folder into a trackable production pipeline for characters, scenes, props, storyboards, and video parts.

Success means a user can import a project, see exactly what is ready or blocked, generate and submit assets in order, recover from API or file errors, and export usable creative outputs on macOS and Windows without developer assistance.

## Brand Personality

Restrained, professional, and production-focused.

The interface should feel calm and competent, closer to Linear, Figma, or other high-trust creation tools than a decorative AI SaaS page. It should support long working sessions, dense production review, and team handoff without visual noise.

## Anti-references

- Do not look like a generic purple AI SaaS dashboard.
- Do not rely on decorative gradients, oversized cards, glass effects, or playful visual gimmicks.
- Do not feel like a programmer-only backend console.
- Do not hide production state behind vague labels such as "processing" without a concrete stage or next action.
- Do not make the user guess whether a failure came from input parsing, API keys, upload, polling, download, or local file writing.

## Design Principles

1. Make the production state obvious: every item should show where it is, what it needs, and what the next available action is.
2. Keep the interface quiet under pressure: use restrained color, clear hierarchy, and familiar controls so the user can focus on decisions.
3. Prefer workflow continuity over isolated screens: importing, generating, submitting, retrying, and downloading should feel like one connected chain.
4. Design for collaboration and handoff: status, errors, paths, and outputs should be understandable to non-technical teammates.
5. Treat cross-platform behavior as part of the product: Windows and macOS paths, scripts, encodings, and startup flows must be first-class.

## Accessibility & Inclusion

Target WCAG 2.1 AA for the working UI.

The app should be keyboard navigable, readable during long sessions, usable without relying on color alone, and respectful of reduced-motion preferences. Error messages should use plain language and include concrete recovery steps.
