# EAS Station - Vultr VPS Deployment Guide

**Last Updated:** November 21, 2025
**Purpose:** Deploy EAS Station on Vultr cloud infrastructure

---

## Overview

This guide covers deploying EAS Station on Vultr VPS servers for:
- Production hosting
- Managed hosting service for customers
- Demo/testing environments
- Multi-instance deployments

**Vultr Benefits:**
- $2.50/month entry-level VPS
- 32 global locations
- Hourly billing
- API for automation
- DDoS protection

---

## Part 1: Vultr Account Setup

### Create Account

1. Go to [vultr.com](https://www.vultr.com)
2. Click **"Sign Up"**
3. Verify email
4. Add payment method (credit card or PayPal)
5. **Optional:** Add $100 credit with promo code (check [Vultr promotions](https://www.vultr.com/promo/))

### Enable API Access

1. Go to **Account → API**
2. Click **"Enable API"**
3. Generate API key (save securely - needed for automation)
4. Whitelist your IP address for API access

---

## Part 2: Choose Server Configuration

### Recommended Configurations

**Development/Testing:**
```
Plan: Cloud Compute - Regular Performance
CPU: 1 vCPU
RAM: 1 GB
Storage: 25 GB SSD
Bandwidth: 1 TB
Cost: $6/month

Use case: Testing, demos, single-user
```

**Small Production (Single Station):**
```
Plan: Cloud Compute - Regular Performance
CPU: 2 vCPU
RAM: 4 GB
Storage: 80 GB SSD
Bandwidth: 3 TB
Cost: $18/month

Use case: Production radio/TV station, light alert volume
```

**Production (Recommended):**
```
Plan: Cloud Compute - Regular Performance
CPU: 2 vCPU
RAM: 8 GB
Storage: 160 GB SSD
Bandwidth: 4 TB
Cost: $36/month

Use case: Heavy alert volume, multiple sources, SDR processing
```

**Multi-Tenant/Managed Hosting:**
```
Plan: Cloud Compute - High Performance
CPU: 4 vCPU
RAM: 16 GB
Storage: 320 GB NVMe
Bandwidth: 5 TB
Cost: $72/month

Use case: Hosting for multiple customers, high availability
```

---

## Part 3: Deploy Your First Server

### Step 1: Choose Server Type

1. Log in to [Vultr](https://my.vultr.com)
2. Click **"Deploy +"** (top right)
3. Select **"Deploy New Server"**

### Step 2: Server Location

Choose based on your audience:
- **New York (NJ)** - US East Coast
- **Atlanta** - US Southeast
- **Chicago** - US Central
- **Dallas** - US South-Central
- **Los Angeles** - US West Coast
- **Seattle** - US Northwest

**Recommendation:** Choose closest to your broadcast location for lowest latency.

### Step 3: Server Type

Select: **Cloud Compute - Regular Performance**
(Unless you need High Performance NVMe)

### Step 4: Server Size

Select based on recommendations above:
- **Testing:** 1GB RAM ($6/mo)
- **Small Production:** 4GB RAM ($18/mo)
- **Production:** 8GB RAM ($36/mo)

### Step 5: Operating System

**Recommended: Ubuntu 22.04 LTS x64**

Why Ubuntu 22.04:
- ✅ Long-term support until 2027
- ✅ Docker officially supported
- ✅ Large community
- ✅ EAS Station tested on Ubuntu

Alternative: Debian 12

### Step 6: Additional Features

**Enable:**
- ✅ **Enable IPv6** (free, future-proof)
- ✅ **Enable Auto Backups** ($1.20/month for 4GB server - highly recommended)
- ✅ **Enable DDoS Protection** (free)

**Optional:**
- ⚠️ Private Networking (if deploying multiple instances)
- ⚠️ Block Storage (if you need more than 160GB)

### Step 7: SSH Keys

**Highly Recommended - Add SSH Key:**

On your local machine:
```bash
# Generate SSH key if you don't have one
ssh-keygen -t ed25519 -C "easstation-vultr"

# Copy public key
cat ~/.ssh/id_ed25519.pub
```

In Vultr:
1. Click **"Add New"** under SSH Keys
2. Paste your public key
3. Name it: "EAS Station Deploy Key"
4. Click **"Add SSH Key"**
5. Select the key for this deployment

### Step 8: Server Hostname & Label

```
Hostname: eas-station-prod-01
Label: EAS Station Production (Customer: YOUR_NAME)
```

### Step 9: Deploy

1. Review configuration
2. Click **"Deploy Now"**
3. Wait 2-5 minutes for provisioning

---

## Part 4: Initial Server Configuration

### Connect to Your Server

Get your server IP from Vultr dashboard, then:

```bash
ssh root@YOUR_SERVER_IP
```

### Update System

```bash
# Update package lists
apt update

# Upgrade all packages
apt upgrade -y

# Install essential packages
apt install -y \
  curl \
  wget \
  git \
  vim \
  htop \
  ufw \
  fail2ban
```

### Configure Firewall

```bash
# Allow SSH
ufw allow 22/tcp

# Allow HTTP
ufw allow 80/tcp

# Allow HTTPS
ufw allow 443/tcp

# Enable firewall
ufw enable

# Check status
ufw status
```

### Set Up Fail2Ban (Brute-Force Protection)

```bash
# Install fail2ban
apt install -y fail2ban

# Enable and start
systemctl enable fail2ban
systemctl start fail2ban

# Check status
fail2ban-client status sshd
```

---

## Part 5: Install Docker

### Install Docker Engine

```bash
# Remove old versions
apt remove docker docker-engine docker.io containerd runc

# Add Docker's official GPG key
apt update
apt install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify installation
docker --version
docker compose version
```

### Enable Docker Service

```bash
systemctl enable docker
systemctl start docker
```

---

## Part 6: Deploy EAS Station

### Clone Repository

```bash
# Navigate to /opt
cd /opt

# Clone EAS Station
git clone https://github.com/KR8MER/eas-station.git
cd eas-station
```

### Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit configuration
nano .env
```

**Key settings to configure:**

```bash
# Secret key - generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your_generated_secret_key_here

# Database credentials
POSTGRES_PASSWORD=strong_random_password_here
POSTGRES_USER=easstation
POSTGRES_DB=easalerts

# Your location (for alert filtering)
DEFAULT_COUNTY_NAME=Your County
DEFAULT_STATE_CODE=OH
DEFAULT_ZONE_CODES=OHZ001,OHC001

# Domain configuration
DOMAIN_NAME=eas-station.yourdomain.com

# EAS broadcast (set to false for managed hosting without transmitter)
EAS_BROADCAST_ENABLED=false
EAS_ORIGINATOR=WXR
EAS_STATION_ID=YOURSTATION

# Admin credentials
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@yourdomain.com
ADMIN_PASSWORD=strong_password_here
```

### Deploy with Docker Compose

```bash
# Start services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f
```

### Wait for Initialization

First startup takes 2-3 minutes:
- PostgreSQL database initialization
- PostGIS extension setup
- Database migrations
- SSL certificate generation (if DOMAIN_NAME set)

---

## Part 7: Configure DNS

### Point Domain to Vultr Server

At your domain registrar (wherever you bought the domain):

**A Record:**
```
Type: A
Host: eas-station (or @​ for root domain)
Value: YOUR_VULTR_SERVER_IP
TTL: 3600
```

**Optional CNAME for www:**
```
Type: CNAME
Host: www
Value: eas-station.yourdomain.com
TTL: 3600
```

Wait 5-60 minutes for DNS propagation.

### Verify DNS

```bash
# Check from your local machine
dig eas-station.yourdomain.com

# Or
nslookup eas-station.yourdomain.com
```

---

## Part 8: SSL Certificate (Let's Encrypt)

### Automatic SSL (if DOMAIN_NAME is set in .env)

EAS Station will automatically request SSL certificate on first startup.

**Check certificate status:**
```bash
docker compose logs nginx | grep -i cert
```

### Manual SSL Setup (if needed)

```bash
# Install certbot
apt install -y certbot python3-certbot-nginx

# Request certificate
certbot --nginx -d eas-station.yourdomain.com

# Test auto-renewal
certbot renew --dry-run
```

### Force HTTPS

Already configured in EAS Station nginx.

---

## Part 9: Access Your EAS Station

### Web Interface

Open browser to:
```
https://eas-station.yourdomain.com
```

**Default credentials:**
- Username: `admin` (or what you set in .env)
- Password: (what you set in ADMIN_PASSWORD)

### Change Admin Password

1. Log in
2. Go to **Settings → Users**
3. Click on admin user
4. Change password

---

## Part 10: Monitoring & Maintenance

### Check System Resources

```bash
# CPU and memory usage
htop

# Docker container stats
docker stats

# Disk usage
df -h

# Logs
docker compose logs -f
```

### Set Up Monitoring Alerts

**Option 1: Vultr Monitoring (Free)**
1. Go to server in Vultr dashboard
2. Click **"Settings" → "Alerts"**
3. Enable:
   - CPU usage > 80%
   - Bandwidth usage > 80%
   - Disk usage > 80%
4. Add email: `support@yourdomain.com`

**Option 2: Uptime Monitoring**
Use free services:
- [UptimeRobot](https://uptimerobot.com) - 50 monitors free
- [Pingdom](https://www.pingdom.com) - Free tier available
- [StatusCake](https://www.statuscake.com) - Free tier

Monitor: `https://eas-station.yourdomain.com/health`

### Automatic Backups

**Database Backup Script:**

Create `/opt/eas-station/backup.sh`:
```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/easstation"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup database
docker compose exec -T alerts-db pg_dump -U easstation easalerts | gzip > $BACKUP_DIR/db_backup_$DATE.sql.gz

# Keep only last 7 days
find $BACKUP_DIR -name "db_backup_*.sql.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
```

Make executable:
```bash
chmod +x /opt/eas-station/backup.sh
```

**Schedule Daily Backups:**
```bash
# Edit crontab
crontab -e

# Add line (runs at 2 AM daily):
0 2 * * * /opt/eas-station/backup.sh >> /var/log/eas-backup.log 2>&1
```

### Update EAS Station

```bash
cd /opt/eas-station

# Pull latest changes
git pull

# Rebuild and restart
docker compose down
docker compose up -d --build

# Check logs
docker compose logs -f
```

---

## Part 11: Multi-Instance Deployment (Managed Hosting)

### Deploy Multiple Instances on One Server

For managed hosting service (hosting multiple customers on one VPS):

**Structure:**
```
/opt/
├── customer1-eas/
│   ├── docker-compose.yml
│   └── .env
├── customer2-eas/
│   ├── docker-compose.yml
│   └── .env
└── customer3-eas/
    ├── docker-compose.yml
    └── .env
```

**Each instance needs:**
1. Unique ports (8001, 8002, 8003...)
2. Unique database names
3. Unique container names
4. Unique domain/subdomain

**Example .env for customer1:**
```bash
# Unique ports
FLASK_PORT=8001
POSTGRES_PORT=5433

# Unique domain
DOMAIN_NAME=customer1.easstation-cloud.com

# Unique database
POSTGRES_DB=easalerts_customer1
```

**Nginx reverse proxy to route domains to ports.**

### Automation with Ansible

For 10+ instances, use Ansible for deployment automation:

1. Create Ansible playbook
2. Define customer variables
3. Deploy with single command
4. See [ANSIBLE_DEPLOYMENT.md] (future doc)

---

## Part 12: Scaling Options

### Vertical Scaling (Upgrade Server)

In Vultr dashboard:
1. Go to server
2. Click **"Settings" → "Change Plan"**
3. Select larger size
4. Server will reboot

**No data loss** - all data preserved.

### Horizontal Scaling (Load Balancing)

For high-availability:
1. Deploy 2+ EAS Station instances
2. Set up Vultr Load Balancer ($10/month)
3. Configure health checks
4. Point DNS to load balancer IP

### Geographic Redundancy

Deploy instances in multiple regions:
- Primary: New York
- Backup: Los Angeles
- Failover with DNS (Route53 or Cloudflare)

---

## Part 13: Security Hardening

### Disable Root SSH Login

```bash
# Edit SSH config
nano /etc/ssh/sshd_config

# Change to:
PermitRootLogin no
PasswordAuthentication no

# Restart SSH
systemctl restart sshd
```

**Create sudo user first:**
```bash
adduser easadmin
usermod -aG sudo easadmin
usermod -aG docker easadmin

# Copy SSH keys
mkdir -p /home/easadmin/.ssh
cp /root/.ssh/authorized_keys /home/easadmin/.ssh/
chown -R easadmin:easadmin /home/easadmin/.ssh
chmod 700 /home/easadmin/.ssh
chmod 600 /home/easadmin/.ssh/authorized_keys
```

### Enable Automatic Security Updates

```bash
apt install -y unattended-upgrades
dpkg-reconfigure --priority=low unattended-upgrades
```

### Configure Docker Security

```bash
# Limit Docker logging
nano /etc/docker/daemon.json
```

Add:
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

Restart Docker:
```bash
systemctl restart docker
```

---

## Part 14: Cost Optimization

### Right-Size Your Server

Monitor for 1 week, then:
- If CPU < 30%: Downgrade
- If CPU > 80%: Upgrade
- If RAM > 90%: Upgrade

### Use Snapshots for Cloning

1. Create snapshot of configured server ($1/month)
2. Use snapshot to deploy new customer instances
3. Faster than manual configuration

### Enable Billing Alerts

In Vultr:
1. Go to **Billing → Alerts**
2. Set alert at $50, $100, $200
3. Prevent surprise bills

---

## Part 15: Backup Strategy

### 3-2-1 Backup Rule

**3 copies** of data:
1. Production database (on server)
2. Daily automated backups (same server)
3. Off-site backup (Vultr Backups or S3)

**2 different media:**
- Server SSD
- Vultr backup system or AWS S3

**1 copy off-site:**
- Vultr automatic backups ($1.20/month per server)

### Vultr Automatic Backups

Enable in server settings:
- Daily snapshots
- 7-day retention
- One-click restore
- $1.20/month for 4GB server

### S3 Backup (Alternative)

```bash
# Install AWS CLI
apt install -y awscli

# Configure
aws configure

# Backup script
#!/bin/bash
BACKUP_FILE="/tmp/db_backup_$(date +%Y%m%d).sql.gz"

docker compose exec -T alerts-db pg_dump -U easstation easalerts | gzip > $BACKUP_FILE

aws s3 cp $BACKUP_FILE s3://your-bucket/eas-backups/

rm $BACKUP_FILE
```

---

## Part 16: Disaster Recovery

### Restore from Backup

**From Vultr automatic backup:**
1. Go to server in dashboard
2. Click **"Backups"**
3. Select backup
4. Click **"Restore"**
5. Server will be restored to that state

**From SQL backup:**
```bash
cd /opt/eas-station

# Stop containers
docker compose down

# Start only database
docker compose up -d alerts-db

# Wait 30 seconds
sleep 30

# Restore from backup
gunzip -c /opt/backups/easstation/db_backup_20251121.sql.gz | \
  docker compose exec -T alerts-db psql -U easstation easalerts

# Restart all services
docker compose up -d
```

---

## Part 17: Performance Tuning

### PostgreSQL Optimization

Create `/opt/eas-station/postgres-tuning.conf`:

```ini
# For 4GB RAM server
shared_buffers = 1GB
effective_cache_size = 3GB
maintenance_work_mem = 256MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
work_mem = 10MB
min_wal_size = 1GB
max_wal_size = 4GB
```

Mount in docker-compose.yml:
```yaml
volumes:
  - ./postgres-tuning.conf:/etc/postgresql/postgresql.conf
```

### Enable Caching

EAS Station uses Redis for caching (optional):

Add to docker-compose.yml:
```yaml
redis:
  image: redis:7-alpine
  restart: unless-stopped
  volumes:
    - redis-data:/data
```

---

## Part 18: Managed Hosting Service

### Offer to Customers

**Package: EAS Station Managed Hosting**
```
$99/month includes:
✓ Dedicated Vultr VPS (4GB RAM)
✓ EAS Station commercial license
✓ SSL certificate
✓ Daily backups
✓ 24/7 monitoring
✓ Software updates
✓ Email support

$149/month for 8GB server
$199/month for high-performance NVMe
```

### Customer Onboarding

1. Customer fills Squarespace form
2. You deploy new instance on Vultr
3. Configure with customer's settings (county, zones)
4. Send credentials
5. Provide training session

### Automation Script

Create `/opt/scripts/new-customer.sh`:
```bash
#!/bin/bash
CUSTOMER_NAME=$1
CUSTOMER_DOMAIN=$2

# Create directory
mkdir -p /opt/${CUSTOMER_NAME}-eas
cd /opt/${CUSTOMER_NAME}-eas

# Clone repository
git clone https://github.com/KR8MER/eas-station.git .

# Generate secrets
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")

# Create .env
cat > .env <<EOF
SECRET_KEY=$SECRET_KEY
POSTGRES_PASSWORD=$DB_PASSWORD
DOMAIN_NAME=$CUSTOMER_DOMAIN
# ... rest of config
EOF

# Deploy
docker compose up -d

echo "Customer $CUSTOMER_NAME deployed at https://$CUSTOMER_DOMAIN"
```

---

## Cost Summary

| Configuration | Vultr Cost | License | Total/Month |
|--------------|-----------|---------|-------------|
| **Self-Hosted (Customer)** | $18 | $995/year = $83 | **$101** |
| **Managed Basic** | $18 | $995/year = $83 | **$101** (sell at $99) |
| **Managed Standard** | $36 | $995/year = $83 | **$119** (sell at $149) |
| **Managed Premium** | $72 | $995/year = $83 | **$155** (sell at $199) |

**Your margin:** $30-50/month per managed customer
**10 customers:** $300-500/month recurring revenue

---

## Support Resources

- **Vultr Docs:** [vultr.com/docs](https://www.vultr.com/docs/)
- **Vultr API:** [vultr.com/api](https://www.vultr.com/api/)
- **Support Tickets:** my.vultr.com (paid plans only)

---

## Next Steps

1. ✅ Create Vultr account
2. ✅ Deploy first server (production or test)
3. ✅ Configure DNS
4. ✅ Set up SSL
5. ✅ Configure monitoring
6. ✅ Set up backups
7. 📄 Link from Squarespace website

---

**Questions?** Contact sales@easstation.com

**Document Version:** 1.0
**Last Updated:** November 21, 2025
