# Security Policy

## Supported Versions

Security fixes are handled on the latest public release of `veloura-audio`.

## Reporting a Vulnerability

Please report suspected vulnerabilities privately through GitHub Security
Advisories for the `VelouraAudio/veloura-audio` repository.

Do not open a public issue for secrets, token exposure, command execution,
stream resolution abuse, or malformed media crashes.

## Runtime Trust Boundaries

Veloura can call FFmpeg and, when the `stream` extra is installed, `yt-dlp`.
Applications that expose URL or search-based playback to public users should
rate-limit requests, keep permission checks in the application, and treat remote
media as untrusted input.

The Discord example includes conservative public-bot defaults, but production
bots should still set a queue cap, resolver timeout, cache limits, and a DJ role
or equivalent permission model for their own server policy.
