# <img src="static/img/eas-system-wordmark.svg" alt="EAS Station" width="192" height="48" style="vertical-align: middle;"> EAS Station™

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue?style=flat-square&logo=gnu&logoColor=white)](https://www.gnu.org/licenses/agpl-3.0)
[![Commercial License](https://img.shields.io/badge/License-Commercial-green?style=flat-square)](LICENSE-COMMERCIAL)
[![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-Compatible-C51A4A?style=flat-square&logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PostgreSQL + PostGIS](https://img.shields.io/badge/PostgreSQL-17%20%2B%20PostGIS-0093D0?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io/)
[![SoapySDR](https://img.shields.io/badge/SoapySDR-enabled-FF6600?style=flat-square)](https://github.com/pothosware/SoapySDR)
[![Icecast](https://img.shields.io/badge/Icecast-2.4.4-1F3B73?style=flat-square)](https://icecast.org/)
[![GPS](https://img.shields.io/badge/Stratum%201-GPS%2FPPS-0F766E?style=flat-square)](#-built-in-stratum-1-ntp-time-source)

> **Open-source emergency alerting infrastructure for research, training, SDR verification, and CAP/SAME experimentation.**

EAS Station™ is a software-defined Emergency Alert System research platform designed for amateur radio operators, emergency communications enthusiasts, developers, broadcasters, and infrastructure researchers.

Built on Raspberry Pi and Linux infrastructure, EAS Station combines:

- CAP/IPAWS alert ingestion
- SAME encoding and decoding
- SDR-based RF verification
- Geographic intelligence via PostGIS
- Real-time monitoring dashboards
- Hardware integration
- GPS-disciplined stratum-1 timing
- Multi-channel alert distribution

...all on commodity hardware consuming roughly **12 watts**.

---

> ⚠️ **Laboratory / Research Use Only**
>
> EAS Station™ is experimental software intended for:
>
> - laboratory environments
> - training
> - research
> - amateur radio experimentation
> - infrastructure development
>
> It is **NOT FCC-certified** and must never be connected to on-air broadcast infrastructure without explicit authorization.

---

# ✨ Core Features

## 📥 Multi-Source Alert Ingestion

- FEMA IPAWS integration
- NOAA/NWS alert ingestion
- API-based weather alert support
- CAP-compatible ingestion workflows
- Automatic alert deduplication
- FIPS and NWS zone targeting
- Geographic filtering via PostGIS

---

## 📻 SAME Encoding & Decoding

- FCC Part 11 SAME header generation
- Attention tone synthesis
- SAME parser and validator
- SAME relay verification
- Real-time SDR SAME decode
- Manual RWT/RMT generation
- Audio forwarding workflows

---

## 📡 SDR Monitoring & RF Verification

- RTL-SDR support
- Airspy support
- SoapySDR abstraction layer
- NOAA Weather Radio monitoring
- FM demodulation
- Live spectrum visualization
- SAME decode verification
- Multi-source monitoring
- Icecast audio streaming

---

## 🗺️ Geographic Intelligence

- PostGIS spatial queries
- Polygon-based alert targeting
- County and zone filtering
- Leaflet-based interactive maps
- TIGER/Line GIS integration
- Shapefile import support

---

## ⚡ Hardware Integration

- GPIO relay control
- OLED status displays
- LED sign integration
- VFD support
- Serial device integration
- Multi-relay workflows
- GPS/PPS hardware support

---

## 🛰️ Built-In Stratum 1 Time Source

EAS Station™ supports GPS-disciplined timing infrastructure using:

- `gpsd`
- `chrony`
- PPS (Pulse Per Second)
- Raspberry Pi GPS HATs

Features include:

- sub-microsecond PPS timing
- stratum-1 NTP serving
- GPS dashboards
- live satellite metrics
- RTC integration
- timing diagnostics

---

## 🌐 Modern Web Dashboard

- Responsive Bootstrap UI
- Dark-mode friendly design
- Live Socket.IO updates
- Alert analytics
- System health monitoring
- GPS dashboards
- RF monitoring views
- Audio monitoring
- Operator settings
- REST API support

---

# 🏗️ Architecture

EAS Station™ is intentionally split into isolated services for operational reliability.

| Service | Responsibility |
|---|---|
| `eas-station-web` | Web UI and REST API |
| `eas-station-poller` | Alert polling and ingestion |
| `eas-station-sdr` | SDR capture and RF decoding |
| `eas-station-audio` | Audio processing and monitoring |
| `eas-station-hardware` | GPIO, displays, and relay control |

Infrastructure components:

- PostgreSQL 17
- PostGIS 3.4
- Redis 7
- NGINX
- Gunicorn
- Icecast
- gpsd
- chrony

---

# 🚀 Quick Start

## Installation

```bash
git clone https://github.com/KR8MER/eas-station.git
cd eas-station
sudo bash install.sh
