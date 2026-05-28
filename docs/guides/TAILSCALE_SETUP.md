# Tailscale VPN Setup Guide

This guide explains how to configure Tailscale on EAS Station™ for secure remote access over a private mesh VPN.

## Table of Contents

- [Overview](#overview)
- [What is Tailscale?](#what-is-tailscale)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Accessing the Tailscale Settings Page](#accessing-the-tailscale-settings-page)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [Connecting and Disconnecting](#connecting-and-disconnecting)
- [Status and Diagnostics](#status-and-diagnostics)
- [Advanced Options](#advanced-options)
- [Troubleshooting](#troubleshooting)
- [Security Considerations](#security-considerations)

---

## Overview

EAS Station™ includes built-in Tailscale VPN management, allowing you to:

- Access your EAS Station™ remotely over a secure, encrypted tunnel
- Join your station to a private tailnet shared with your team
- Avoid exposing ports to the public internet
- Manage Tailscale settings, connection state, and diagnostics entirely from the EAS Station™ web interface

---

## What is Tailscale?

[Tailscale](https://tailscale.com) is a zero-configuration VPN built on WireGuard. Instead of managing firewall rules or port forwarding, you simply install Tailscale on each device and they can reach each other securely over a private network called a **tailnet**.

Key concepts:

| Term | Description |
|------|-------------|
| **Tailnet** | Your private network of Tailscale-connected devices |
| **Peer** | Another device on your tailnet |
| **Auth Key** | A pre-shared key for headless/automated device authentication |
| **Exit Node** | A tailnet peer that routes your internet traffic |
| **MagicDNS** | Automatic hostname resolution for tailnet peers |
| **Shields Up** | Blocks all incoming connections from tailnet peers |

---

## Prerequisites

Before configuring Tailscale in EAS Station™, you need:

1. **A Tailscale account** — Free at [tailscale.com](https://tailscale.com). Supports up to 100 devices at no cost.
2. **Tailscale installed on the system** — See [Installation](#installation) below.
3. **System access level `system.configure`** — Only administrators can access Tailscale settings.

---

## Installation

Tailscale must be installed on the EAS Station™ system before it can be configured. Installation is performed entirely through the EAS Station™ web interface — no command-line access is required.

1. Log in to the EAS Station™ web interface
2. Navigate to **Admin → Tailscale**
3. Click the **Diagnostics** tab
4. If Tailscale is not yet installed, the Installation Status section will show **Not Installed** along with an **Install Tailscale** button
5. Click **Install Tailscale** and confirm the prompt
6. The installer will run in the background and display live output. Installation typically completes in under a minute
7. When complete, the page will refresh and show Tailscale as **Installed**

The installer uses the [official Tailscale install script](https://tailscale.com/install.sh) and automatically enables the `tailscaled` system service.

> **Note:** The EAS Station™ system must have internet access during installation to download Tailscale from the official repository.

---

## Accessing the Tailscale Settings Page

1. Log in to the EAS Station™ web interface
2. Click **Admin** in the top navigation bar
3. Select **Tailscale** from the admin menu

The Tailscale page has three tabs:

| Tab | Purpose |
|-----|---------|
| **Configuration** | Save settings such as hostname, auth key, and VPN options |
| **Status** | View connection state, Tailscale IP, and tailnet peers; connect/disconnect |
| **Diagnostics** | Check installation status and ping tailnet peers |

---

## Configuration

All Tailscale settings are saved in the EAS Station™ database and applied the next time you connect.

### Configuration Fields

| Field | Description | Default |
|-------|-------------|---------|
| **Enable Tailscale** | Master toggle. When disabled, Tailscale will not start automatically. | Off |
| **Hostname** | Custom device name in the tailnet (e.g., `eas-station-kc1abc`). Leave blank to use the system hostname. Alphanumeric and hyphens only, max 63 characters. | *(system hostname)* |
| **Auth Key** | Pre-shared authentication key from the Tailscale admin console. Allows headless authentication without browser login. | *(empty)* |
| **Accept Routes** | Accept subnet routes advertised by other tailnet peers. | Off |
| **Advertise Routes** | Advertise local subnets to the tailnet (comma-separated CIDR, e.g. `192.168.1.0/24`). | *(empty)* |
| **Advertise as Exit Node** | Allow other tailnet peers to route their internet traffic through this device. | Off |
| **Shields Up** | Block all incoming connections from tailnet peers. The device is still reachable for outgoing connections only. | Off |
| **Accept DNS** | Use MagicDNS from the tailnet for hostname resolution. | On |

### Saving Settings

Click **Save Settings** after making changes. Settings are stored in the database and take effect on the next connect.

> **Auth Key Security:** Auth keys are stored in the database and masked in the UI. Use Tailscale reusable or ephemeral keys for automated deployments. Keys can be revoked from the Tailscale admin console at any time.

---

## Authentication

There are two ways to authenticate the EAS Station™ device with your tailnet.

### Option 1: Auth Key (Recommended for Headless Deployment)

1. Log in to the [Tailscale admin console](https://login.tailscale.com/admin/settings/keys)
2. Generate an **Auth Key** (reusable or one-time)
3. Paste the key into the **Auth Key** field in EAS Station™ settings
4. Save settings, then click **Connect** on the Status tab

The device authenticates automatically without requiring browser interaction.

### Option 2: Browser Login

Use this method if you do not have an auth key, or if your key has expired.

1. Leave the **Auth Key** field empty and save settings
2. Go to the **Status** tab and click **Connect**
3. If authentication is required, a **Login URL** button will appear
4. Click the button to open the Tailscale authentication URL
5. Complete login in your browser

The device is added to your tailnet once authentication is complete.

---

## Connecting and Disconnecting

All connection management is done from the **Status** tab.

### Connecting

1. Ensure Tailscale is installed (check the **Diagnostics** tab)
2. Configure your settings and save (see [Configuration](#configuration))
3. Click **Connect**

EAS Station™ will:
- Start the `tailscaled` daemon if it is not running
- Enable the daemon to start automatically on boot
- Run `tailscale up` with your saved settings

### Disconnecting

Click **Disconnect** on the **Status** tab. This runs `tailscale down`, which brings the VPN tunnel down but leaves the device registered in your tailnet.

### Logging Out

Click **Logout** to fully remove the device from the tailnet. The device will need to re-authenticate the next time you connect.

---

## Status and Diagnostics

### Status Tab

When connected, the Status tab shows:

| Field | Description |
|-------|-------------|
| **Status** | `Connected`, `Needs Login`, `Stopped`, or `Not Installed` |
| **Tailscale IP** | Your device's `100.x.x.x` tailnet IP address |
| **Hostname** | Device name as it appears in the tailnet |
| **DNS Name** | MagicDNS hostname (e.g., `eas-station.tail1234.ts.net`) |
| **Tailnet** | Name of your tailnet organization |
| **Peers** | List of other devices currently in your tailnet, with their IPs and online status |

### Diagnostics Tab

The Diagnostics tab provides:

- **Installation Status** — Confirms whether Tailscale is installed and shows the installed version
- **Daemon Status** — Shows whether `tailscaled` is running
- **Peer Ping** — Enter a peer hostname or Tailscale IP address and click **Ping** to test connectivity

---

## Advanced Options

### Advertising Subnet Routes

If other tailnet peers need access to devices on the same LAN as EAS Station™, you can advertise the local subnet:

1. Enter the CIDR notation of your subnet in **Advertise Routes** (e.g., `192.168.1.0/24`)
2. Multiple subnets can be specified as a comma-separated list
3. Save settings and reconnect

> **Note:** Route advertisement must also be approved in the Tailscale admin console before other peers can use the route.

### Exit Node

Enabling **Advertise as Exit Node** allows other tailnet peers to route all their internet traffic through this EAS Station™ device. This is typically not needed for EAS operations but may be useful in custom network configurations.

### Shields Up

**Shields Up** prevents any tailnet peer from initiating connections to this device. Outbound connections from this device to the tailnet still work. Use this if you want the EAS Station™ to be part of the tailnet for outbound monitoring purposes only.

### Accept DNS

When enabled, the device uses Tailscale's MagicDNS, which allows resolving other tailnet peers by hostname (e.g., `ping other-device.tail1234.ts.net`). Disable this if it conflicts with local DNS configuration.

---

## Troubleshooting

### Tailscale shows "Not Installed"

Tailscale is not installed on the system. Go to the **Diagnostics** tab, click **Install Tailscale**, and confirm the prompt. The system must have internet access to download the installer.

### Status shows "Needs Login"

The device requires authentication. Either:
- Add a valid **Auth Key** in the Configuration tab, save, and reconnect
- Click **Connect**, then use the **Login URL** button to authenticate via browser

### Status shows "Connected" but I cannot reach the device

- Verify you are connecting to the correct Tailscale IP (`100.x.x.x` range shown in the Status tab)
- Check that **Shields Up** is not enabled, which blocks all incoming connections
- Ensure the tailnet peer you are connecting from is authenticated and online
- Check that any local firewall on the EAS Station™ host allows traffic on the Tailscale interface (`tailscale0`)

### Peer ping fails

- Confirm the target peer is currently online (shown in the peer list on the Status tab)
- Use the exact hostname or Tailscale IP as shown in the peer list
- Ensure both devices are connected to the tailnet

### Settings not applying after save

Click **Disconnect**, then **Connect** again to apply the new settings. Tailscale settings are passed to `tailscale up` at connect time, so an active connection must be restarted to pick up changes.

### Auth key rejected

- Verify the key was copied correctly with no extra spaces
- Check whether the key has expired or was already used (if one-time)
- Generate a new key from the [Tailscale admin console](https://login.tailscale.com/admin/settings/keys)

---

## Security Considerations

- **Access control:** Only users with `system.configure` permission can access Tailscale settings. Guard admin credentials carefully.
- **Auth keys:** Store auth keys securely. Anyone with an auth key can add a device to your tailnet. Use short-lived or ephemeral keys where possible, and revoke unused keys from the Tailscale admin console.
- **Tailnet ACLs:** The Tailscale admin console allows defining Access Control Lists (ACLs) to restrict which tailnet peers can communicate with each other. Configure ACLs to limit access to your EAS Station™.
- **Shields Up:** Consider enabling **Shields Up** if the EAS Station™ should not accept any inbound connections from tailnet peers.
- **Public internet:** Tailscale access does not replace firewall rules for your public internet interface. Continue following the guidance in [Firewall Requirements](../troubleshooting/FIREWALL_REQUIREMENTS.md).

---

## Related Documentation

- [HTTPS Setup](HTTPS_SETUP.md) — Configuring SSL/TLS for the web interface
- [Security Guide](../security/SECURITY.md) — Overview of EAS Station™ security and best practices
- [Firewall Requirements](../troubleshooting/FIREWALL_REQUIREMENTS.md) — Network port requirements

---

**Last Updated:** 2026-02-17
**Author:** KR8MER Amateur Radio Emergency Communications
