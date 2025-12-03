# EAS Station Marketing Materials

## Marketing Brochure

This document describes professional marketing materials for the EAS Station project.

### Files

- **EAS-Station-Brochure.pdf** - 3-page professional marketing brochure (PDF format)
- **EAS-Station-Brochure.html** - Source HTML file for the brochure (for editing)

### Brochure Contents

The marketing brochure is a 3-page professional document that includes:

#### Page 1: Cover
- EAS Station logo and branding
- Professional tagline and value proposition
- Hero messaging highlighting the software-defined replacement for commercial EAS hardware
- Target audience identification (Broadcasters, Amateur Radio, Emergency Management)

#### Page 2: Features & Architecture
- **8 Key Features** with icons and descriptions:
  - Multi-Source Ingestion (NOAA, IPAWS, custom CAP)
  - FCC-Compliant SAME encoding
  - Geographic Intelligence with PostGIS
  - SDR Verification
  - Built-in HTTPS security
  - Modern Web UI
  - Hardware Integration (GPIO, LED, OLED)
  - Comprehensive REST API
  
- **System Architecture Diagram**:
  - Visual flow showing alert sources → poller → database → web/audio services
  - Benefits listed: Reliable, Simple, Fast, Debuggable

#### Page 3: Use Cases & Contact
- **4 Target Markets**:
  - Broadcasters (replace expensive commercial encoders)
  - Amateur Radio (emergency communications and training)
  - Alert Distribution (custom systems and geographic targeting)
  - Developers (research, experimentation, integrations)

- **System Requirements**:
  - Hardware specifications
  - Software dependencies
  - Recommended configurations

- **Contact Information**:
  - GitHub repository URL
  - Documentation references
  - Quick-start information
  - Dual licensing details
  - Laboratory use disclaimer

### Design Features

- **Professional gradient design** with purple/blue color scheme
- **Responsive layout** optimized for 8.5" x 11" US Letter format
- **High-quality graphics** including icons, diagrams, and architecture flows
- **Clear typography** using modern sans-serif fonts
- **Structured information hierarchy** with sections, cards, and callouts
- **Print-optimized** with proper page breaks and margins

### Editing the Brochure

To make changes to the brochure:

1. Edit the `EAS-Station-Brochure.html` file
2. Open it in a web browser to preview changes
3. Convert to PDF using Chrome/Chromium:

```bash
# Overwrites existing PDF
google-chrome --headless --disable-gpu \
  --print-to-pdf=EAS-Station-Brochure.pdf \
  --print-to-pdf-no-header \
  EAS-Station-Brochure.html

# Or create a versioned copy
google-chrome --headless --disable-gpu \
  --print-to-pdf=EAS-Station-Brochure-$(date +%Y%m%d).pdf \
  --print-to-pdf-no-header \
  EAS-Station-Brochure.html
```

Or use any HTML-to-PDF converter that supports modern CSS (Grid, Flexbox, Gradients).

### Distribution

The brochure is suitable for:

- **Trade shows and conferences**
- **Email campaigns and newsletters**
- **Website downloads**
- **Sales presentations**
- **Partner outreach**
- **Educational materials**

### Licensing

The brochure content is subject to the same licensing as the EAS Station project:
- Open source content (AGPL v3) for non-commercial use
- Commercial licensing available for proprietary applications

Copyright © 2025 Timothy Kramer (KR8MER)

---

For questions or customization requests, please visit the project repository:
https://github.com/KR8MER/eas-station
