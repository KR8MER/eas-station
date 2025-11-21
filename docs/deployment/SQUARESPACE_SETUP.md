# EAS Station - Squarespace Commercial Website Setup

**Last Updated:** November 21, 2025
**Purpose:** Create a professional commercial presence for EAS Station

---

## Overview

This guide walks you through setting up a complete commercial website for EAS Station on Squarespace, including:
- Product pages for commercial licensing
- Pricing and checkout integration
- Documentation hosting
- Lead generation and contact forms
- Domain configuration

**Estimated Time:** 2-4 hours
**Cost:** $16-$49/month (Squarespace) + $12-20/year (domain)

---

## Prerequisites

- Squarespace account (create at [squarespace.com](https://www.squarespace.com))
- Domain name (can purchase through Squarespace or transfer existing)
- Payment processor account (Stripe/PayPal for commercial licensing sales)
- Logo and branding assets

---

## Part 1: Squarespace Account Setup

### Step 1: Choose Your Plan

**Recommended Plan: Business ($23/month annual)**
- ✅ Custom domain
- ✅ Professional email (Google Workspace integration)
- ✅ Advanced website analytics
- ✅ Promotional pop-ups and banners
- ✅ Commerce features (for selling licenses)
- ✅ CSS/JavaScript customization

**Alternative: Commerce Basic ($27/month annual)**
- All Business features
- ✅ 0% transaction fees
- ✅ Point of sale
- ✅ Checkout on custom domain
- Better for high-volume license sales

### Step 2: Start Your Website

1. Go to [squarespace.com](https://www.squarespace.com)
2. Click **"Get Started"**
3. Choose template category: **"Professional Services"** or **"Technology"**
4. **Recommended templates:**
   - **"Beaumont"** - Clean, tech-focused
   - **"Forma"** - Modern, professional
   - **"Lusaka"** - Product-focused

---

## Part 2: Domain Configuration

### Option A: Purchase Domain Through Squarespace

1. Go to **Settings → Domains**
2. Click **"Get a Domain"**
3. Search for your desired domain:
   - `easstation.com` (primary recommendation)
   - `eas-station.com`
   - `easstation.net`
4. Complete purchase ($20/year average)

### Option B: Connect Existing Domain

If you already own `easstation.com` or similar:

1. Go to **Settings → Domains → Use a Domain I Own**
2. Enter your domain name
3. Follow DNS configuration instructions:

**DNS Records to Add at Your Registrar:**
```
Type: A
Host: @
Value: 198.185.159.144

Type: A
Host: @
Value: 198.185.159.145

Type: CNAME
Host: www
Value: ext-cust.squarespace.com
```

4. Wait 24-48 hours for DNS propagation

### Custom Email Setup

**Recommended: Google Workspace** ($6/user/month)
1. Go to **Settings → Email → Google Workspace**
2. Create email: `sales@easstation.com`, `support@easstation.com`
3. Configure MX records (automatic through Squarespace)

---

## Part 3: Website Structure

### Recommended Site Map

```
Home (/)
├── Features (/features)
├── Pricing (/pricing)
├── Documentation (/docs)
│   ├── Getting Started
│   ├── Installation Guide
│   ├── Hardware BOM
│   └── API Reference
├── Hardware (/hardware)
├── Download (/download)
├── Support (/support)
├── Blog (/blog)
├── About (/about)
└── Contact (/contact)
```

### Create Pages

1. Click **Pages** in left sidebar
2. Click **"+"** to add new page
3. Choose **"Blank"** for most pages
4. Add pages as listed above

---

## Part 4: Homepage Design

### Hero Section

**Content:**
```
Headline: EAS Station
Subheadline: Software-Defined Emergency Alert System

Replace $5,000 EAS encoders with commodity hardware.
FCC-compliant SAME encoding, PostGIS intelligence, SDR verification.

[Get Started] [View Pricing] [Documentation]
```

**Background:**
- Upload the EAS Station wordmark SVG
- Or use a clean photo of Raspberry Pi + Argon ONE case
- Keep it professional and technical

### Features Section

**Three-Column Layout:**

```
Column 1: Multi-Source Ingestion
NOAA Weather, IPAWS federal alerts, custom CAP feeds

Column 2: FCC-Compliant SAME
Specific Area Message Encoding per FCC Part 11

Column 3: Geographic Intelligence
PostGIS spatial filtering with county/state/polygon support
```

### Pricing Teaser

```
Pricing That Makes Sense
Starting at $995/year or $2,995 perpetual

Early Adopter Special: $1,797
[View Full Pricing →]
```

### Social Proof

```
Built by amateur radio operators and broadcast engineers.
Open-source core (AGPL v3) with commercial licensing available.

[GitHub Stars Badge]
[License: Dual Licensed Badge]
```

---

## Part 5: Pricing Page

### Layout

Use **"Pricing Table"** block:

**Column 1: Open Source**
```
Free
AGPL v3 License

✓ Full source code
✓ Community support
✓ Must share modifications
✓ Non-commercial use

[Download on GitHub]
```

**Column 2: Single Station** ⭐ Most Popular
```
$995/year
or $2,995 perpetual

✓ Commercial use
✓ No source disclosure
✓ Email support (48hr)
✓ Security updates
✓ Single installation

Early Adopter: $1,797
[Contact Sales]
```

**Column 3: Multi-Station**
```
$4,995/year
or $12,995 perpetual

✓ Up to 10 installations
✓ Priority support (24hr)
✓ Quarterly consultations
✓ Multi-site coordination

Early Adopter: $7,797
[Contact Sales]
```

**Column 4: Enterprise**
```
$19,995/year
or $49,995 perpetual

✓ Unlimited installations
✓ Premium support (12hr)
✓ Custom development (40hr/yr)
✓ White-label options

Early Adopter: $29,997
[Contact Sales]
```

### Add Comparison Table

Below pricing cards, add a detailed feature comparison table (import from your PRICING.md).

---

## Part 6: Download/Getting Started Page

### GitHub Integration

**Content:**
```
Get Started with EAS Station

1. Clone the repository
   git clone https://github.com/KR8MER/eas-station.git

2. Configure environment
   cp .env.example .env
   # Edit .env with your settings

3. Launch with Docker
   docker compose up -d

[View Full Documentation] [Hardware BOM]
```

### System Requirements

List from README:
- Docker Engine 24+
- PostgreSQL 14+ with PostGIS
- 4GB RAM (8GB recommended)
- Internet connection

### Quick Links

```
→ Installation Guide
→ Configuration Reference
→ Hardware Bill of Materials
→ Troubleshooting
→ GitHub Repository
→ API Documentation
```

---

## Part 7: Documentation Integration

### Option A: Embed GitHub Pages

If you set up GitHub Pages for `docs/`:
1. Add **"Embed"** block
2. Use iframe to embed documentation
3. URL: `https://kr8mer.github.io/eas-station/`

### Option B: Recreate in Squarespace

1. Create **"Documentation"** folder under Pages
2. Add child pages for each major doc section:
   - Getting Started
   - Installation
   - Configuration
   - API Reference
   - Hardware Setup
3. Copy content from markdown files
4. Use Squarespace's markdown block for formatting

---

## Part 8: Contact & Lead Generation

### Contact Form

1. Add **"Form"** block to Contact page
2. Configure fields:
   - Name (required)
   - Email (required)
   - Company/Organization
   - Use Case (dropdown):
     - Radio/TV Broadcast
     - Emergency Management
     - Amateur Radio
     - Education/Research
     - Other
   - License Interest (dropdown):
     - Single Station
     - Multi-Station
     - Enterprise
     - OEM/Integration
   - Message (required)

3. Form Settings:
   - Send to: `sales@easstation.com`
   - Confirmation message: "Thanks! We'll respond within 24 hours."
   - Enable reCAPTCHA

### Lead Capture Popup

1. Go to **Marketing → Promotional Pop-up**
2. Create popup:
   ```
   Get Early Adopter Pricing

   Lock in 40% discount before FCC certification.
   Single station license: $1,797 perpetual (reg. $2,995)

   [Email field]
   [Get Pricing Info]
   ```
3. Display settings:
   - Show after 30 seconds
   - Don't show more than once per visitor
   - Mobile-friendly

---

## Part 9: E-Commerce Setup (License Sales)

### Enable Commerce

1. Go to **Commerce → Payments**
2. Connect **Stripe** (recommended):
   - Create Stripe account at [stripe.com](https://stripe.com)
   - Connect to Squarespace
   - Configure tax settings
3. Alternative: PayPal

### Create Products

**Product 1: Single Station License (Perpetual)**
```
Name: EAS Station - Single Station License (Perpetual)
Price: $2,995
SKU: EAS-SINGLE-PERP

Description:
Perpetual commercial license for one EAS Station installation.
Includes 1 year of updates and support.

- No AGPL obligations
- Commercial use permitted
- Email support (48-hour response)
- Security patches and updates
- Lifetime license to current major version

Digital product: Customer receives license key via email.

[Image: EAS Station logo or product screenshot]
```

**Product 2: Early Adopter - Single Station**
```
Name: EAS Station - Single Station (Early Adopter)
Price: $1,797
SKU: EAS-SINGLE-EARLY
On Sale: 40% off (show original $2,995)

Limited time offer until FCC certification.
Same benefits as regular perpetual license.

Stock: Limited (creates urgency)
```

Repeat for Multi-Station and Enterprise tiers.

### Product Variants

For annual vs perpetual:
1. Edit product
2. Add **Variants**:
   - Annual Subscription: $995/year
   - Perpetual License: $2,995

### Digital Delivery

1. Go to **Product → Advanced**
2. Enable **"This is a digital product"**
3. Upload **"License Agreement PDF"** as downloadable file
4. Add **"License Key"** in order confirmation email

---

## Part 10: Blog for Updates

### Create Blog

1. Go to **Pages → Add Page → Blog**
2. Name it **"Updates"** or **"Blog"**

### Sample Posts

**Post 1: "Introducing EAS Station Commercial Licensing"**
- Announce commercial availability
- Link to pricing page
- Explain early adopter program

**Post 2: "Hardware Bill of Materials Released"**
- Announce BOM document
- Highlight $450 complete system vs. $5K DASDEC
- Link to BOM page

**Post 3: "How EAS Station Saves Broadcasters $4,750 Per Installation"**
- Cost breakdown
- TCO analysis
- Case studies

---

## Part 11: Analytics & Tracking

### Google Analytics

1. Go to **Settings → Analytics → Google Analytics**
2. Create Google Analytics 4 property
3. Add Measurement ID (G-XXXXXXXXXX)
4. Enable e-commerce tracking

### Conversion Goals

Track:
- Contact form submissions
- License purchases
- Documentation page views
- Pricing page views
- GitHub clicks

---

## Part 12: SEO Optimization

### Site-Wide SEO

1. Go to **Settings → SEO**
2. Configure:
   ```
   Site Title: EAS Station | Open-Source Emergency Alert System

   Meta Description:
   Software-defined EAS encoder/decoder for broadcasters. Replace $5K
   commercial hardware with Raspberry Pi. FCC-compliant SAME encoding,
   PostGIS intelligence, SDR verification. Open-source & commercial licenses.

   Keywords:
   EAS encoder, emergency alert system, SAME encoder, DASDEC alternative,
   broadcast automation, IPAWS, CAP alerts, FCC Part 11, radio automation
   ```

### Page-Level SEO

For each page, edit **Page Settings → SEO**:

**Homepage:**
```
Title: EAS Station - Open-Source Emergency Alert System
Description: Software-defined EAS encoder/decoder. Replace expensive
commercial hardware with Raspberry Pi. AGPL open-source + commercial licensing.
```

**Pricing:**
```
Title: Pricing - EAS Station Commercial Licensing
Description: Commercial licenses starting at $995/year. Early adopter
pricing $1,797 perpetual. 40-60% savings vs. DASDEC.
```

**Documentation:**
```
Title: Documentation - EAS Station Setup Guide
Description: Complete installation and configuration guide for EAS Station.
Docker deployment, hardware setup, FCC compliance.
```

---

## Part 13: Mobile Optimization

### Mobile Settings

1. Go to **Design → Mobile**
2. Adjust layout for mobile:
   - Simplify navigation
   - Stack pricing columns vertically
   - Enlarge buttons ("Get Started", "Contact Sales")
   - Test forms on mobile

### Mobile Menu

Configure hamburger menu:
```
Home
Features
Pricing
Documentation
Hardware
Download
Contact
```

---

## Part 14: Custom CSS/Branding

### Add Custom CSS

1. Go to **Design → Custom CSS**
2. Add branding:

```css
/* Primary brand color - adjust to match your logo */
:root {
  --brand-primary: #2563eb; /* Blue */
  --brand-accent: #10b981;  /* Green */
}

/* CTA buttons */
.sqs-block-button-element {
  background-color: var(--brand-primary) !important;
  border-radius: 6px;
  font-weight: 600;
  padding: 14px 32px;
}

.sqs-block-button-element:hover {
  background-color: var(--brand-accent) !important;
  transform: translateY(-2px);
  transition: all 0.2s;
}

/* Code blocks for documentation */
code {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Monaco', 'Courier New', monospace;
  font-size: 0.9em;
}

pre {
  background: #1e293b;
  color: #f1f5f9;
  padding: 20px;
  border-radius: 8px;
  overflow-x: auto;
}

/* Pricing cards */
.pricing-card {
  border: 2px solid #e2e8f0;
  border-radius: 12px;
  transition: all 0.3s;
}

.pricing-card:hover {
  border-color: var(--brand-primary);
  box-shadow: 0 10px 30px rgba(37, 99, 235, 0.1);
  transform: translateY(-4px);
}

.pricing-card.featured {
  border-color: var(--brand-primary);
  border-width: 3px;
}
```

---

## Part 15: Legal Pages

### Create Required Pages

**Privacy Policy**
1. Use [Squarespace Privacy Generator](https://www.squarespace.com/privacy-policy-generator)
2. Add page to footer

**Terms of Service**
1. Create page with commercial license terms
2. Link to LICENSE-COMMERCIAL from GitHub
3. Add to footer

**Refund Policy**
```
30-day money-back guarantee for annual subscriptions.
90-day money-back guarantee for perpetual licenses.
Must meet documented specifications.
```

---

## Part 16: Email Marketing Integration

### Squarespace Email Campaigns

1. Go to **Marketing → Email Campaigns**
2. Create welcome sequence:
   - Email 1: Thank you for interest
   - Email 2: Getting started guide
   - Email 3: Early adopter pricing reminder
   - Email 4: Case studies and testimonials

### Newsletter Signup

Add to footer:
```
Stay Updated
Get news about FCC certification, feature releases, and pricing updates.

[Email field] [Subscribe]
```

---

## Part 17: Launch Checklist

### Pre-Launch

- [ ] All pages created and populated
- [ ] Pricing tables configured
- [ ] Contact forms tested
- [ ] Domain connected and working
- [ ] SSL certificate active (https://)
- [ ] Mobile layout tested
- [ ] Products/licenses created in Commerce
- [ ] Payment processing tested
- [ ] Google Analytics connected
- [ ] SEO metadata complete
- [ ] Legal pages published
- [ ] Logo and branding consistent

### Launch

1. Go to **Settings → General**
2. Set **Password Protection** to **"Public"**
3. Announce on:
   - GitHub repository README
   - Amateur radio forums
   - LinkedIn
   - Twitter/X
   - Reddit (r/amateurradio, r/broadcasting)

---

## Part 18: Post-Launch Optimization

### A/B Testing

Test variations:
- Hero headline copy
- Pricing display (monthly vs annual vs perpetual)
- CTA button text ("Get Started" vs "Contact Sales" vs "Buy Now")
- Early adopter discount messaging

### Content Updates

Monthly:
- Blog post about development progress
- Customer success story
- Technical deep-dive
- FCC certification updates

### SEO Monitoring

Track in Google Search Console:
- Search queries driving traffic
- Click-through rates
- Page indexing status
- Mobile usability

---

## Integration with Vultr

**Link to managed hosting:**
```
Don't want to self-host?

We offer fully-managed EAS Station hosting on Vultr infrastructure.
Starting at $49/month (includes license, hosting, support).

[Learn More About Managed Hosting →]
```

Create a **"Managed Hosting"** page that links to Vultr deployment options.

---

## Cost Breakdown

| Item | Cost | Frequency |
|------|------|-----------|
| Squarespace Business Plan | $23 | Monthly |
| Domain (easstation.com) | $20 | Yearly |
| Google Workspace (2 emails) | $12 | Monthly |
| Stripe fees | 2.9% + $0.30 | Per transaction |
| **Total** | **~$35/month** | - |

**ROI:** One Single Station license sale ($2,995) covers ~7 years of website costs.

---

## Support Resources

- **Squarespace Help:** [support.squarespace.com](https://support.squarespace.com)
- **Template Demos:** [squarespace.com/templates](https://www.squarespace.com/templates)
- **Circle Community:** [community.squarespace.com](https://community.squarespace.com)

---

## Next Steps

1. **Complete Squarespace setup** (this guide)
2. **Set up Vultr deployment** (see VULTR_DEPLOYMENT.md)
3. **Connect payment processing** (Stripe)
4. **Launch marketing campaign**
5. **Monitor analytics and conversions**

---

**Questions?** Contact sales@easstation.com

**Document Version:** 1.0
**Last Updated:** November 21, 2025
