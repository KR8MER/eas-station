# Complete Development Setup Guide for zencoder.ai Integration

**Transform your development workflow!** This comprehensive guide shows you how to set up your Raspberry Pi or Linux server so that **zencoder.ai** (https://zencoder.ai) can work alongside you like a pair programmer sitting at your desk. Zencoder will be able to:

- ✅ **Run your code** and see the output in real-time
- ✅ **Debug issues** by setting breakpoints and inspecting variables
- ✅ **View database transactions** and query data directly
- ✅ **Access the web interface** to test UI changes
- ✅ **Monitor system logs** and service status
- ✅ **Execute tests** and verify fixes immediately

This guide will hold your hand through every step of the setup process, from SSH configuration to database access to debugging tools. By the end, zencoder.ai will have complete visibility into your EAS Station development environment.

> **💡 New to this setup?** Don't worry! This guide assumes no prior experience with remote development. We'll explain everything step-by-step.

---

## Table of Contents

- [Why This Setup is Perfect for zencoder.ai](#why-this-setup-is-perfect-for-zenco derai)
- [What You'll Learn](#what-youll-learn)
- [Prerequisites](#prerequisites)
- [Part 1: Setting Up Your IDE (PyCharm or VS Code)](#part-1-setting-up-your-ide-pycharm-or-vs-code)
- [Part 2: Enabling zencoder.ai to Run Code](#part-2-enabling-zenco derai-to-run-code)
- [Part 3: Database Access for zencoder.ai](#part-3-database-access-for-zenco derai)
- [Part 4: Viewing the Web Interface](#part-4-viewing-the-web-interface)
- [Part 5: Debugging with zencoder.ai](#part-5-debugging-with-zenco derai)
- [Part 6: Advanced Features](#part-6-advanced-features)
- [Complete zencoder.ai Workflow Examples](#complete-zenco derai-workflow-examples)
- [Troubleshooting Common Issues](#troubleshooting-common-issues)
- [Best Practices](#best-practices)
- [Quick Reference Commands](#quick-reference-commands)
- [Summary and Next Steps](#summary-and-next-steps)

---

## Why This Setup is Perfect for zencoder.ai

**zencoder.ai** (https://zencoder.ai) is an AI coding assistant that needs full access to your development environment to be truly effective. Think of it as having an expert developer sitting next to you who can:

### What Makes This Special

Traditional development workflows have limitations:
- ❌ Code runs in isolated environments
- ❌ AI can't see real-time errors
- ❌ No access to live databases
- ❌ Can't test on actual hardware
- ❌ Limited to suggesting code, not testing it

**With this setup, zencoder.ai becomes a true pair programmer:**
- ✅ **Executes code directly** on your Raspberry Pi/server
- ✅ **Sees actual output** - errors, logs, database queries
- ✅ **Tests in real environment** - real hardware, real services
- ✅ **Debugs with breakpoints** - inspect variables, step through code
- ✅ **Views the web UI** - test frontend changes immediately
- ✅ **Monitors services** - systemd status, log files, resource usage
- ✅ **Queries database** - see actual alert data, verify changes
- ✅ **Iterates instantly** - make changes, test, fix, repeat

### How It Works

```
┌─────────────────────────────────────────────────────────┐
│  Your Computer (Windows/Mac/Linux)                     │
│  ┌──────────────────────────────────────────────────┐  │
│  │  IDE (PyCharm / VS Code)                         │  │
│  │  • You edit code                                 │  │
│  │  • zencoder.ai suggests changes                  │  │
│  │  • Changes sync to server instantly              │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     │ SSH Connection                    │
│                     │ (encrypted tunnel)                │
└─────────────────────┼───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Linux Server / Raspberry Pi                            │
│  ┌──────────────────────────────────────────────────┐  │
│  │  /opt/eas-station/                               │  │
│  │  • Code runs HERE                                │  │
│  │  • zencoder.ai executes commands HERE            │  │
│  │  • Debugger attaches HERE                        │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  PostgreSQL Database                             │  │
│  │  • zencoder.ai queries HERE                      │  │
│  │  • See real alert data                           │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Web Server (Nginx → Gunicorn → Flask)          │  │
│  │  • Access at https://your-server-ip              │  │
│  │  • zencoder.ai can test UI changes               │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Systemd Services                                │  │
│  │  • eas-station-web, audio, pollers, etc.        │  │
│  │  • zencoder.ai can restart and monitor          │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Key Insight**: Your code doesn't run on your local machine - it runs on the Linux server via SSH. This means zencoder.ai can access everything: real hardware, live database, running services, log files, and more!

---

## What You'll Learn

By the end of this guide, you'll have configured:

1. **SSH Remote Development** - Edit code locally, run it on the server
2. **Python Remote Interpreter** - Execute Python code on the server from your IDE
3. **Database Access** - Connect to PostgreSQL from multiple tools
4. **Web UI Testing** - Access the EAS Station web interface
5. **Remote Debugging** - Set breakpoints, inspect variables, step through code
6. **Service Management** - Start/stop/restart systemd services
7. **Log Monitoring** - View real-time service logs
8. **zencoder.ai Integration** - Enable AI assistant to do all of the above

This is a **production-grade development setup** used by professional developers. You'll learn skills that apply to any remote development project, not just EAS Station.

---

---

## Part 1: Setting Up Your IDE (PyCharm or VS Code)

This section will help you choose and configure your IDE for remote development. Both PyCharm Professional and VS Code work excellently - choose based on your preference.

### Step 1.1: Choose Your IDE

#### Option A: VS Code (Recommended for Beginners - FREE)

**Why VS Code?**
- ✅ Completely free, no license needed
- ✅ Fast and lightweight
- ✅ Excellent remote SSH support
- ✅ Great Python support with extensions
- ✅ Works on Windows, Mac, Linux
- ✅ Perfect for zencoder.ai integration

**Get it**: Download from [https://code.visualstudio.com/](https://code.visualstudio.com/)

#### Option B: PyCharm Professional (Best for Python - FREE for Open Source)

**Why PyCharm Professional?**
- ✅ Best-in-class Python IDE
- ✅ Powerful debugging and refactoring
- ✅ Database tools built-in (DataGrip)
- ✅ **Free with open source license**

**Get it free for open source**:

Since `eas-station` is an open source project under AGPL-3.0, you qualify for a free license:

1. Go to: [JetBrains Open Source License Application](https://www.jetbrains.com/community/opensource/#support)
2. Click **Apply Now**
3. Fill out the form:
   - **Project Name**: EAS Station
   - **Project URL**: `https://github.com/KR8MER/eas-station`
   - **License Type**: AGPL-3.0
   - **Your Role**: Contributor or Maintainer
4. JetBrains typically responds within a few days

While waiting for approval, use the [30-day free trial](https://www.jetbrains.com/pycharm/download/) or start with VS Code.

**⚠️ Don't Use PyCharm Community Edition** - It lacks remote SSH development features required for this workflow.

---

### Step 1.2: Configure VS Code for Remote Development

**Follow these steps if you chose VS Code:**

#### Install Required Extensions

1. **Open VS Code**
2. Click the **Extensions** icon in the left sidebar (or press `Ctrl+Shift+X` / `Cmd+Shift+X`)
3. Search for and install these extensions:
   - **Remote - SSH** (by Microsoft) - Essential for remote development
   - **Python** (by Microsoft) - Python language support
   - **PostgreSQL** (by Chris Kolkman) - Database management (optional but helpful)

#### Connect to Your Server

1. **Press `F1`** (or `Ctrl+Shift+P` / `Cmd+Shift+P`) to open the command palette
2. Type: `Remote-SSH: Connect to Host` and press Enter
3. Type: `eas-station@YOUR_SERVER_IP` 
   - Replace `YOUR_SERVER_IP` with your server's IP address (e.g., `192.168.1.100`)
   - If you don't know your server's IP, see [Finding Your Server IP](#finding-your-server-ip) below
4. Press Enter
5. Select the platform: **Linux**
6. Enter your password when prompted
7. Wait for VS Code to connect (this may take 30-60 seconds the first time)

#### Open the EAS Station Directory

1. Once connected, click **File** → **Open Folder**
2. Type or navigate to: `/opt/eas-station`
3. Click **OK**
4. Enter your password again if prompted

#### Configure Python Interpreter

1. **Press `Ctrl+Shift+P` / `Cmd+Shift+P`** to open command palette
2. Type: `Python: Select Interpreter`
3. Choose: `/opt/eas-station/venv/bin/python` (the virtual environment Python)
   - If you don't see it, click **Enter interpreter path** and type it manually

**✅ VS Code is now configured!** Skip to [Part 2](#part-2-enabling-zenco derai-to-run-code).

---

### Step 1.3: Configure PyCharm Professional for Remote Development

**Follow these steps if you chose PyCharm:**

#### Set Up SSH Deployment

1. **Open PyCharm** and create a new project or open an existing one
2. Go to: **File** → **Settings** (Windows/Linux) or **PyCharm** → **Preferences** (Mac)
3. Navigate to: **Build, Execution, Deployment** → **Deployment**
4. Click the **+** button and select **SFTP**
5. Name it: `EAS Station Server`
6. Configure the **Connection** tab:
   - **Type**: SFTP
   - **Host**: Your server's IP address (e.g., `192.168.1.100`)
   - **Port**: `22`
   - **Username**: `eas-station` (or `pi` if on Raspberry Pi)
   - **Auth type**: Password
   - **Password**: Your server password (save it)
   - Click **Test Connection** - you should see "Successfully connected"
7. Configure the **Mappings** tab:
   - **Local path**: Your local project folder (can be empty for now)
   - **Deployment path**: `/opt/eas-station`
   - **Web path**: (leave empty)
8. Click **OK**

#### Set Up SSH Interpreter

1. Go to: **File** → **Settings** → **Project** → **Python Interpreter**
2. Click the **gear icon** ⚙️ → **Add...**
3. Select **SSH Interpreter**
4. Choose **Existing server configuration** and select the server you just created
5. Click **Next**
6. Set the interpreter path: `/opt/eas-station/venv/bin/python`
7. Configure sync folders:
   - **Local**: Your project folder
   - **Remote**: `/opt/eas-station`
8. Click **Finish**
9. Wait for PyCharm to sync files and index the project (this can take 2-5 minutes)

**✅ PyCharm is now configured!** Continue to Part 2.

---

### Finding Your Server IP

**If you don't know your server's IP address:**

Connect to the server directly (keyboard + monitor, or existing SSH) and run:

```bash
hostname -I
```

You'll see output like: `192.168.1.100 172.17.0.1`

The first IP address (e.g., `192.168.1.100`) is your server's local network IP.

**Write this down** - you'll need it throughout this guide!

---

## Prerequisites

### What You Need Before Starting

**On the Linux Server (Raspberry Pi or Debian/Ubuntu):**
- EAS Station installed via bare metal installation (`install.sh`)
- SSH server enabled
- Installation directory: `/opt/eas-station`
- Services running via systemd
- Network connection (same network as your computer, or internet-accessible)

**On Your Development Computer (Windows/Mac/Linux):**
- PyCharm Professional OR VS Code (we'll help you choose)
- Network access to the Linux server
- SSH client (built into modern Windows, Mac, and Linux)
- Web browser (for accessing the UI)

**If You Haven't Installed EAS Station Yet:**

```bash
# On the Linux server:
cd ~/
git clone https://github.com/KR8MER/eas-station.git
cd eas-station
sudo ./install.sh
```

See [QUICKSTART-BARE-METAL.md](../QUICKSTART-BARE-METAL.md) for detailed installation instructions.

### Skill Level

**Don't worry if you're new to this!** This guide is designed for beginners and will explain:
- How SSH works and how to use it
- How to connect to a remote server
- How to use an IDE with remote development
- How to access databases remotely
- How to configure debugging tools

If you can follow step-by-step instructions, you can do this!

---

## Part 2: Enabling zencoder.ai to Run Code

Now that your IDE is connected to the server, let's configure zencoder.ai to have **complete access** to execute commands, run Python code, and manage the system.

### Step 2.1: Understanding How zencoder.ai Works with Your IDE

**Let me explain what's happening:**

When you installed VS Code or PyCharm and connected it to your server via SSH:
- Your IDE is now a "remote control" for the server
- When you open a file in the IDE, you're editing a file **on the server**, not your local computer
- When you run code, it runs **on the server**
- When zencoder.ai suggests code changes, those changes happen **on the server**

Think of it like this:
```
Your Computer                    The Server (Raspberry Pi)
┌─────────────┐                 ┌──────────────────────┐
│   Your IDE  │  SSH Connection │  EAS Station Files   │
│  (VSCode or │────────────────>│  /opt/eas-station/   │
│  PyCharm)   │    (encrypted)  │                      │
│             │                 │  Python runs HERE    │
│ zencoder.ai │────────────────>│  Database is HERE    │
│ sends       │                 │  Redis is HERE       │
│ commands    │                 │  Services run HERE   │
└─────────────┘                 └──────────────────────┘
```

**Why this matters:**
- zencoder.ai can see everything on the server (files, databases, logs, services)
- zencoder.ai can run commands as if it's logged into the server directly
- Changes happen instantly - no "upload" or "deploy" step needed

Now let's give zencoder.ai permission to do everything!

### Step 2.2: Grant sudo Permissions for Service Management

**What are we doing here?**

The EAS Station runs as several "services" (background programs) managed by systemd. To let zencoder.ai restart services, view logs, and manage the system, we need to give special permissions.

Normally, when you want to do system administration tasks, Linux asks for your password (that's what `sudo` does - it means "run this as the administrator"). But we want zencoder.ai to do these things automatically without stopping to ask for a password every time.

**Let's set this up step by step:**

#### Step A: Connect to Your Server

Open a terminal on your computer:
- **Windows**: Press `Win+R`, type `cmd`, press Enter
- **Mac**: Press `Cmd+Space`, type `terminal`, press Enter  
- **Linux**: Press `Ctrl+Alt+T`

Then connect to your server:

```bash
ssh eas-station@YOUR_SERVER_IP
```

Replace `YOUR_SERVER_IP` with the actual IP (like `192.168.1.100`).

**What you'll see:**
```
eas-station@192.168.1.100's password:
```

Type your password (you won't see it as you type - that's normal for security) and press Enter.

**You're now connected!** You'll see something like:
```
eas-station@raspberrypi:~$
```

This is the server's command prompt. Any commands you type now run on the server.

#### Step B: Edit the Permissions File

Now we'll edit the "sudoers" file - this controls who can do what on the system.

Type this command:

```bash
sudo visudo
```

Press Enter. You'll see a text file open up in a text editor called `nano`.

**Understanding what you see:**

You'll see a file with lots of comments (lines starting with `#`). Don't worry about those - we're just adding to the end.

#### Step C: Add the New Permissions

**Use your arrow keys** to scroll to the very bottom of the file.

**Copy and paste these lines** at the end (or type them carefully):

```bash
# ==============================================================================
# EAS STATION PERMISSIONS FOR ZENCODER.AI
# ==============================================================================
# These permissions allow the eas-station user (and zencoder.ai working
# through your IDE) to manage services, view logs, and access system resources
# WITHOUT needing to type a password every time.
#
# This is safe because:
# - Only the eas-station user has these permissions
# - Commands are restricted to specific programs
# - Access requires SSH authentication first
# ==============================================================================

# -------------------- Service Management --------------------
# Start, stop, restart EAS Station services
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl start eas-station*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl stop eas-station*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl restart eas-station*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl reload eas-station*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl status eas-station*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl daemon-reload
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl edit eas-station*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl revert eas-station*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl list-units eas-station*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl list-dependencies eas-station*

# -------------------- Log Viewing --------------------
# View service logs (essential for debugging)
eas-station ALL=(ALL) NOPASSWD: /bin/journalctl -u eas-station*
eas-station ALL=(ALL) NOPASSWD: /bin/journalctl *
eas-station ALL=(ALL) NOPASSWD: /usr/bin/tail /var/log/*
eas-station ALL=(ALL) NOPASSWD: /usr/bin/less /var/log/*
eas-station ALL=(ALL) NOPASSWD: /usr/bin/cat /var/log/*

# -------------------- System Monitoring --------------------
# Check what's running, network connections, resource usage
eas-station ALL=(ALL) NOPASSWD: /bin/netstat
eas-station ALL=(ALL) NOPASSWD: /bin/ss
eas-station ALL=(ALL) NOPASSWD: /usr/bin/lsof
eas-station ALL=(ALL) NOPASSWD: /usr/bin/ps
eas-station ALL=(ALL) NOPASSWD: /usr/bin/top
eas-station ALL=(ALL) NOPASSWD: /usr/bin/htop

# -------------------- Database Access --------------------
# Connect to PostgreSQL database
eas-station ALL=(ALL) NOPASSWD: /usr/bin/psql
eas-station ALL=(ALL) NOPASSWD: /bin/su - postgres

# -------------------- Redis Access --------------------
# Access Redis (used for real-time communication between services)
eas-station ALL=(ALL) NOPASSWD: /usr/bin/redis-cli

# -------------------- File Management --------------------
# Fix file ownership and permissions if needed
eas-station ALL=(ALL) NOPASSWD: /bin/chown -R eas-station\:eas-station /opt/eas-station/*
eas-station ALL=(ALL) NOPASSWD: /bin/chmod * /opt/eas-station/*
eas-station ALL=(ALL) NOPASSWD: /bin/ls -la /opt/eas-station/*
eas-station ALL=(ALL) NOPASSWD: /usr/bin/find /opt/eas-station/*

# -------------------- Network Testing --------------------
# Test network connectivity
eas-station ALL=(ALL) NOPASSWD: /bin/ping
eas-station ALL=(ALL) NOPASSWD: /usr/bin/curl
eas-station ALL=(ALL) NOPASSWD: /usr/bin/wget
eas-station ALL=(ALL) NOPASSWD: /usr/bin/nc

# -------------------- Package Management --------------------
# Install Python packages (for dependencies)
eas-station ALL=(ALL) NOPASSWD: /opt/eas-station/venv/bin/pip install *
eas-station ALL=(ALL) NOPASSWD: /opt/eas-station/venv/bin/pip3 install *
eas-station ALL=(ALL) NOPASSWD: /usr/bin/apt-get update
eas-station ALL=(ALL) NOPASSWD: /usr/bin/apt-get install *

# -------------------- Text Editors --------------------
# Edit files (useful for quick config changes)
eas-station ALL=(ALL) NOPASSWD: /usr/bin/nano /opt/eas-station/*
eas-station ALL=(ALL) NOPASSWD: /usr/bin/vim /opt/eas-station/*
```

#### Step D: Save the File

**To save and exit:**

1. Press `Ctrl+X` (this means "exit")
2. You'll see: `Save modified buffer?` - Press `Y` for "yes"
3. You'll see the filename - just press `Enter` to confirm

**What you should see:**
```
[ Wrote 50 lines ]
```

That means it saved successfully!

#### Step E: Test the Permissions

Let's make sure it worked. Try these commands (they should NOT ask for a password):

```bash
# Check web service status
sudo systemctl status eas-station-web.service
```

Press `q` to exit when you're done reading.

```bash
# View last 10 log lines
sudo journalctl -u eas-station-web.service -n 10
```

```bash
# Test Redis connection
sudo redis-cli ping
```

You should see: `PONG`

**If any command asks for a password**, something went wrong. Double-check the sudoers file by running `sudo visudo` again.

**✅ If no passwords were requested, you're done with this step!**

### Step 2.3: Install Python Debugging Support (debugpy)

**What is debugpy?**

`debugpy` is a tool that lets you pause your running code at specific lines (called "breakpoints") and look inside to see:
- What values variables have
- What the program is doing at that exact moment
- Where errors are happening

Think of it like pausing a video to examine a single frame - except you're pausing your code!

**Let's install it:**

In your SSH session (or in your IDE's terminal), run:

```bash
# Install debugpy into the EAS Station virtual environment
sudo -u eas-station /opt/eas-station/venv/bin/pip install debugpy
```

**What this command does:**
- `sudo -u eas-station` = Run as the eas-station user
- `/opt/eas-station/venv/bin/pip` = Use the Python package installer from the virtual environment
- `install debugpy` = Install the debugpy package

You'll see output like:
```
Collecting debugpy
  Downloading debugpy-1.8.0-cp311-cp311-linux_armv7l.whl (3.4 MB)
Installing collected packages: debugpy
Successfully installed debugpy-1.8.0
```

**Verify it installed correctly:**

```bash
sudo -u eas-station /opt/eas-station/venv/bin/python -c "import debugpy; print('✅ debugpy installed successfully')"
```

You should see: `✅ debugpy installed successfully`

**✅ Great! Now your server can support debugging.**

---

### Step 2.4: Understanding Breakpoints (What They Are and How to Use Them)

**What is a breakpoint?**

Imagine you're reading a recipe while cooking, but you want to pause after step 3 to check if the sauce looks right. A breakpoint is like putting a bookmark at step 3 - the program will run normally until it hits that line, then it **stops and waits** for you to look around.

**Why are breakpoints useful?**

Instead of adding `print()` statements everywhere to see what's happening, you can:
1. Set a breakpoint on the line you're curious about
2. Run the program
3. When it hits that line, everything pauses
4. You can examine all variables, see the call stack, and step through code line by line

**Real example:**

Let's say you have this code:
```python
def calculate_alert_priority(alert):
    severity = alert.get('severity')  # ← Set breakpoint here
    urgency = alert.get('urgency')
    priority = severity * urgency
    return priority
```

If you set a breakpoint on line 2 (where the arrow is), when the function runs:
1. The program will run normally until it reaches that line
2. **Everything stops** - the function hasn't finished yet
3. You can now inspect:
   - What is `alert`? (maybe it's `{'severity': 3, 'urgency': 2}`)
   - What is `severity`? (maybe it's `3`)
   - You can even change the values and see what happens!
4. Then you can "step" to the next line and watch `urgency` get set
5. Continue stepping to see `priority` calculated

**How to set a breakpoint:**

**In VS Code:**
- Click in the left margin (the gray area left of the line numbers) next to any line
- A red dot appears = breakpoint is set
- Click again to remove it

**In PyCharm:**
- Click in the left margin next to any line
- A red dot appears = breakpoint is set  
- Click again to remove it

**What happens when code hits a breakpoint:**

Your IDE will highlight the current line in yellow and show you:
- **Variables panel** - see all current variable values
- **Call stack** - how did we get to this line? What functions called what?
- **Debug console** - type Python commands to explore

**Debugger controls (buttons you'll see):**

- **Continue (▶️)** - Resume running until next breakpoint
- **Step Over (⤵️)** - Execute this line and go to the next line in this function
- **Step Into (⬇️)** - If this line calls a function, go inside that function
- **Step Out (⬆️)** - Finish this function and return to the caller
- **Stop (⏹️)** - Stop debugging completely

**A simple analogy:**

Think of debugging like watching a movie:
- **Normal running** = Watching the movie at normal speed
- **Breakpoint** = Pausing at a specific scene
- **Step Over** = Advance one frame (but don't go into flashbacks)
- **Step Into** = Jump into a flashback scene to see details
- **Step Out** = Exit the flashback and return to main story
- **Continue** = Resume playing until next pause point

**We'll set up actual debugging in Part 5**, but now you understand what it means!

### Step 2.4: Configure Redis Access

**What is Redis?**

Redis is like a super-fast sticky note board that the EAS Station services use to talk to each other in real-time. For example:
- The audio service writes: "I'm processing an alert right now"
- The web service reads: "Oh, there's an alert being processed - show that on the dashboard"

For zencoder.ai to see what services are doing, it needs to read these "sticky notes."

**Let's set it up:**

#### Step A: Check Redis is Running

```bash
sudo systemctl status redis-server
```

You should see `Active: active (running)` in green. If not, start it:

```bash
sudo systemctl start redis-server
```

#### Step B: Test the Connection

```bash
redis-cli ping
```

You should see: `PONG`

This is like knocking on a door and hearing someone answer - Redis is alive and responding!

#### Step C: Explore What's in Redis

**See all the "keys" (sticky notes) currently stored:**

```bash
redis-cli --scan
```

You might see output like:
```
eas-audio-metrics
eas-sdr-status
eas-current-alert
eas-service-health
```

These are the different pieces of information services are sharing.

**View a specific piece of information:**

```bash
# See audio service metrics
redis-cli GET eas-audio-metrics
```

You might see JSON data like:
```json
{"service":"audio","status":"running","last_check":"2025-01-15T10:30:00Z"}
```

**Monitor Redis in real-time (see all commands as they happen):**

```bash
redis-cli monitor
```

Now Redis will show you every command as services communicate:
```
1642234567.890123 [0 127.0.0.1:45678] "SET" "eas-audio-metrics" "{...}"
1642234568.123456 [0 127.0.0.1:45679] "GET" "eas-audio-metrics"
```

This is incredibly useful for debugging! You can see exactly what services are saying to each other.

Press `Ctrl+C` to stop monitoring.

#### Step D: Useful Redis Commands for Debugging

```bash
# List all keys
redis-cli KEYS '*'

# Get a value
redis-cli GET key-name

# Delete a key (if testing)
redis-cli DEL key-name

# See how long until a key expires
redis-cli TTL key-name

# Get info about Redis itself
redis-cli INFO

# See how many keys exist
redis-cli DBSIZE
```

**✅ Now zencoder.ai can monitor Redis to understand service communication!**

### Step 2.5: Test Code Execution with zencoder.ai

Now let's verify zencoder.ai can execute code. This is where everything comes together!

#### Step A: Open Your IDE's Terminal

**In VS Code:**
- Press `` Ctrl+` `` (that's Ctrl and the backtick key, usually above Tab)
- OR click **Terminal** → **New Terminal** from the menu

**In PyCharm:**
- Click **View** → **Tool Windows** → **Terminal**
- OR click the **Terminal** tab at the bottom of the window

**Important:** The terminal should show you're connected to the **server**, not your local computer.

You should see:
```bash
eas-station@raspberrypi:/opt/eas-station$
```

NOT:
```bash
C:\Users\YourName>           # ← This would be Windows local
yourname@yourlaptop:~$       # ← This would be Linux/Mac local
```

If you see your local computer's prompt, you need to reconnect to the server in your IDE.

#### Step B: Verify Python Environment

Let's check that Python is set up correctly:

```bash
# 1. Check which Python we're using
which python
```

**Expected output:** `/opt/eas-station/venv/bin/python`

If you see `/usr/bin/python` or something else, the virtual environment isn't activated. Run:
```bash
source /opt/eas-station/venv/bin/activate
```

You should now see `(venv)` at the start of your prompt:
```bash
(venv) eas-station@raspberrypi:/opt/eas-station$
```

#### Step C: Test Basic Python Execution

```bash
# 2. Run a simple Hello World
python -c "print('✅ Hello from EAS Station!')"
```

**What this does:**
- `python` = Run the Python interpreter
- `-c` = Execute the following code as a command
- The text in quotes is Python code

**Expected output:** `✅ Hello from EAS Station!`

#### Step D: Test Flask (The Web Framework)

```bash
# 3. Verify Flask is available
python -c "from flask import Flask; print('✅ Flask is ready')"
```

**Expected output:** `✅ Flask is ready`

If you see an error like `ModuleNotFoundError: No module named 'flask'`, the virtual environment isn't activated properly.

#### Step E: Test Database Connection Library

```bash
# 4. Verify database library
python -c "import psycopg2; print('✅ Database library available')"
```

**Expected output:** `✅ Database library available`

#### Step F: Test Service Status

```bash
# 5. Check all EAS Station services
sudo systemctl status eas-station.target
```

**What you should see:**
```
● eas-station.target - EAS Station Services
     Loaded: loaded
     Active: active
```

And a list of services:
```
● eas-station-web.service          - EAS Station Web Service
● eas-station-audio.service        - EAS Station Audio Service
● eas-station-noaa-poller.service  - NOAA Weather Alert Poller
...
```

Press `q` to quit.

#### Step G: View Recent Logs

```bash
# 6. See what the web service has been doing
sudo journalctl -u eas-station-web.service -n 20
```

**What this does:**
- `journalctl` = View system logs
- `-u eas-station-web.service` = Filter to just this service
- `-n 20` = Show the last 20 lines

You'll see log entries like:
```
Jan 15 10:30:00 raspberrypi gunicorn[1234]: [INFO] Starting gunicorn 21.2.0
Jan 15 10:30:01 raspberrypi gunicorn[1234]: [INFO] Listening at: http://0.0.0.0:5000
```

#### Step H: Test Redis

```bash
# 7. Verify Redis responds
redis-cli ping
```

**Expected output:** `PONG`

#### Step I: List Running Python Processes

```bash
# 8. See all Python programs currently running
ps aux | grep python
```

You'll see output like:
```
eas-station  1234  0.5  2.1  123456  54321 ?  Ss  10:30  0:02 /opt/eas-station/venv/bin/python /opt/eas-station/app.py
eas-station  1235  0.3  1.8  111222  33444 ?  Ss  10:30  0:01 /opt/eas-station/venv/bin/python /opt/eas-station/eas_monitoring_service.py
```

This shows you which Python programs are running and using how much CPU and memory.

#### Step J: Test zencoder.ai Can Run These Commands

Now, the moment of truth! Ask zencoder.ai to run one of these commands. For example, in your IDE, you might say:

> "zencoder.ai, can you check the status of the web service?"

zencoder.ai should be able to run:
```bash
sudo systemctl status eas-station-web.service
```

And report back what it found!

**✅ If all these commands worked, zencoder.ai now has full code execution access!**

#### What Just Happened?

You've proven that:
1. ✅ Your IDE's terminal connects to the server
2. ✅ Python works in the virtual environment
3. ✅ Flask and database libraries are available
4. ✅ Services can be checked without passwords
5. ✅ Logs can be viewed
6. ✅ Redis responds
7. ✅ System processes can be inspected

This means zencoder.ai can now:
- Run Python code
- Check if services are working
- Read logs to diagnose problems
- Query Redis
- Monitor system resources

**Next, we'll set up database access so zencoder.ai can query actual alert data!**

---

## Part 3: Database Access for zencoder.ai

The EAS Station stores all alert data in a PostgreSQL database with PostGIS spatial extensions. This section will show you how to let zencoder.ai query the database, view alert data, check geographic data, and understand database transactions.

### Step 3.1: Understanding the Database Setup

**What is the database storing?**

The EAS Station database contains:
- **Alert data** - Every emergency alert received (weather warnings, AMBER alerts, etc.)
- **Geographic boundaries** - County and state boundaries for targeting alerts
- **System configuration** - Settings, user accounts, API keys
- **Historical logs** - Past alerts, broadcast history, verification data

**Database Details:**
- **Database Name**: `alerts`
- **Database User**: `eas_station`
- **Database Location**: Running on the server at `localhost:5432`
- **Type**: PostgreSQL 17 with PostGIS 3.4 (spatial/geographic features)

### Step 3.2: Find Your Database Password

The database password was auto-generated during installation and stored in the `.env` file.

**In your IDE terminal, run:**

```bash
# View the database password
grep POSTGRES_PASSWORD /opt/eas-station/.env
```

**Expected output:**
```
POSTGRES_PASSWORD=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

**Copy this password** - you'll need it multiple times. Save it somewhere safe (like a password manager or secure note).

**Understanding the .env file:**

The `.env` file contains all sensitive configuration:
- Database passwords
- Secret keys for encryption
- API keys
- Domain names

**⚠️ Important:** Never commit the `.env` file to Git - it contains secrets!

### Step 3.3: Access the Database via Command Line (psql)

The simplest way to query the database is using `psql`, the PostgreSQL command-line tool.

#### Method A: Connect as the eas_station User

**In your IDE terminal, run:**

```bash
# Connect to the database
psql -h localhost -U eas_station -d alerts
```

It will ask for a password - paste the password you found in Step 3.2 and press Enter.

**What you'll see:**
```
Password for user eas_station: 
psql (17.0)
Type "help" for help.

alerts=>
```

The `alerts=>` is your database prompt - you can now type SQL commands!

#### Try These Basic Queries:

**1. See all tables:**
```sql
\dt
```

**Expected output:**
```
List of relations
 Schema |      Name       | Type  |    Owner    
--------+-----------------+-------+-------------
 public | cap_alerts      | table | eas_station
 public | alert_history   | table | eas_station
 public | users           | table | eas_station
 public | counties        | table | eas_station
```

**2. Count how many alerts are in the database:**
```sql
SELECT COUNT(*) FROM cap_alerts;
```

**Expected output:**
```
 count 
-------
   142
(1 row)
```

**3. View the 5 most recent alerts:**
```sql
SELECT id, event, headline, sent 
FROM cap_alerts 
ORDER BY sent DESC 
LIMIT 5;
```

**Expected output:**
```
  id  |        event        |              headline               |          sent           
------+---------------------+-------------------------------------+-------------------------
 1234 | Severe Thunderstorm | Severe Thunderstorm Warning issued  | 2025-01-15 10:30:00+00
 1233 | Flash Flood         | Flash Flood Warning for...          | 2025-01-15 08:15:00+00
```

**4. Find alerts by event type:**
```sql
SELECT event, COUNT(*) as count 
FROM cap_alerts 
GROUP BY event 
ORDER BY count DESC;
```

This shows how many of each type of alert you've received.

**5. View geographic data (PostGIS!):**
```sql
SELECT name, state_code, ST_AsText(ST_Centroid(geom)) as center_point
FROM counties
LIMIT 3;
```

This shows county names and their geographic center points!

**Useful psql Commands:**

```sql
\dt              -- List all tables
\d table_name    -- Describe a table's structure
\l               -- List all databases
\q               -- Quit psql
\?               -- Show all commands
```

**To exit psql:**
```sql
\q
```

Or press `Ctrl+D`

#### Method B: Connect as the Postgres Super User

For administrative tasks, you might need postgres user access:

```bash
# Switch to postgres user and connect
sudo -u postgres psql -d alerts
```

You won't need a password with this method. The prompt will show:
```
alerts=#
```

Notice the `#` instead of `=>` - this means you're a superuser!

**✅ Now zencoder.ai can query the database via psql commands!**

### Step 3.4: Access Database via Web Interface (pgAdmin)

**What is pgAdmin?**

pgAdmin is a graphical web interface for managing PostgreSQL databases. It's already installed on your server! Think of it like opening your database in a web browser instead of typing commands.

**Why use pgAdmin?**
- ✅ Visual interface - see tables, columns, data in a nice GUI
- ✅ No command typing - click to run queries
- ✅ Query builder - build SQL visually
- ✅ Export data - download query results as CSV/JSON
- ✅ Perfect for sharing screens with zencoder.ai

#### Step A: Access pgAdmin in Your Browser

**Open your web browser** (Chrome, Firefox, Safari, Edge) and navigate to:

```
https://YOUR_SERVER_IP/pgadmin4
```

Replace `YOUR_SERVER_IP` with your server's IP (like `https://192.168.1.100/pgadmin4`)

**⚠️ Security Warning:**

Your browser will show a warning like:
- "Your connection is not private"
- "NET::ERR_CERT_AUTHORITY_INVALID"

This is normal! The server uses a self-signed SSL certificate. Click **Advanced** and then **Proceed to [IP address]** (Chrome) or **Accept the Risk and Continue** (Firefox).

This is safe because you're connecting to your own server on your local network.

#### Step B: Log In to pgAdmin

You'll see a login page. Enter:
- **Email**: The administrator email you created during EAS Station installation
- **Password**: The administrator password you created during installation

**Note:** These are NOT the database credentials - they're your pgAdmin web interface credentials. They were set up when you installed EAS Station.

**Forgot your pgAdmin password?** You can reset it:
```bash
# On the server:
sudo -u postgres /usr/pgadmin4/bin/setup-web.sh
```

Follow the prompts to set a new email and password.

#### Step C: Add the EAS Station Database Server (First Time Only)

If this is your first time using pgAdmin, you need to add the database server:

1. In the left panel, **right-click** on **Servers**
2. Click **Register** → **Server**
3. A dialog box appears

**General Tab:**
- **Name**: `EAS Station` (or any name you like)

Click the **Connection** tab:

**Connection Tab:**
- **Host name/address**: `localhost` (because pgAdmin is running on the same server as the database)
- **Port**: `5432`
- **Maintenance database**: `alerts`
- **Username**: `eas_station`
- **Password**: The database password from Step 3.2

**☑️ Check this box:** **Save password?** (so you don't have to enter it every time)

Click **Save**

#### Step D: Explore the Database

Now you should see in the left panel:
```
Servers
└── EAS Station
    └── Databases
        └── alerts
            └── Schemas
                └── public
                    └── Tables
                        ├── cap_alerts
                        ├── counties
                        ├── alert_history
                        └── ...
```

**Click to expand** each level.

**To view data in a table:**
1. Expand **Servers** → **EAS Station** → **Databases** → **alerts** → **Schemas** → **public** → **Tables**
2. **Right-click** on `cap_alerts`
3. Click **View/Edit Data** → **All Rows**

You'll see a spreadsheet-like view of all alerts!

#### Step E: Run Custom Queries

**To write your own SQL queries:**

1. **Right-click** on **alerts** database
2. Click **Query Tool**
3. A SQL editor appears

**Try this query:**
```sql
SELECT 
    event,
    headline,
    urgency,
    severity,
    sent,
    expires
FROM cap_alerts
WHERE urgency = 'Immediate'
ORDER BY sent DESC
LIMIT 10;
```

**Click the ▶️ Play button** (or press F5)

The results appear below!

**Export results:**
- Click the **Download** icon (💾) above the results
- Choose **CSV** or **JSON**
- The file downloads to your computer

**✅ Now you (and zencoder.ai) can explore the database visually!**

### Step 3.5: Access Database from IDE (PyCharm Database Tools / VS Code Extension)

If you want to query the database without leaving your IDE:

#### For PyCharm Professional (with DataGrip):

1. Open **Database** tool window: **View** → **Tool Windows** → **Database**
2. Click **+** → **Data Source** → **PostgreSQL**
3. Configure connection:
   - **Host**: `localhost` (code runs on server via SSH)
   - **Port**: `5432`
   - **Database**: `alerts`
   - **User**: `eas_station`
   - **Password**: Your database password from Step 3.2
4. Click **Test Connection** - should see "Succeeded"
5. Click **OK**

Now you can browse tables, run queries, and view data in PyCharm!

#### For VS Code (with PostgreSQL Extension):

1. Open **Extensions** (`Ctrl+Shift+X`)
2. Search for **PostgreSQL** by Chris Kolkman
3. Install it
4. Press `Ctrl+Shift+P` and type: `PostgreSQL: New Connection`
5. Enter connection details when prompted:
   - **Host**: `localhost`
   - **Username**: `eas_station`
   - **Password**: Your database password
   - **Port**: `5432`
   - **Use SSL**: No
   - **Database**: `alerts`

Now you can run SQL queries from VS Code!

**✅ Multiple ways to access the database are now set up!**

### Step 3.6: Monitor Database Transactions in Real-Time

**What are database transactions?**

Every time the EAS Station saves an alert, updates a record, or queries data, it's a "transaction" with the database. Being able to see these transactions helps zencoder.ai understand:
- What the application is doing
- Why certain data appears (or doesn't)
- Where performance bottlenecks are
- When errors occur

#### Method A: PostgreSQL Query Log

Enable query logging to see every SQL statement executed:

**Step 1: Enable logging**

```bash
# Edit PostgreSQL configuration
sudo nano /etc/postgresql/*/main/postgresql.conf
```

**Step 2: Find and change these lines** (use `Ctrl+W` to search):

```
log_statement = 'all'          # Log all SQL statements
log_duration = on              # Log how long each query takes
log_line_prefix = '%t [%p] %u@%d '  # Add timestamps and user info
```

**Step 3: Restart PostgreSQL**

```bash
sudo systemctl restart postgresql
```

**Step 4: Watch the log in real-time**

```bash
# View the PostgreSQL log as transactions happen
sudo tail -f /var/log/postgresql/postgresql-17-main.log
```

You'll see every SQL query as it happens:
```
2025-01-15 10:30:15 [1234] eas_station@alerts LOG:  statement: SELECT * FROM cap_alerts WHERE urgency='Immediate'
2025-01-15 10:30:15 [1234] eas_station@alerts LOG:  duration: 2.456 ms
```

Press `Ctrl+C` to stop watching.

**⚠️ Warning:** Logging all statements creates large log files. Disable it when not debugging:
```
log_statement = 'none'
```

#### Method B: PostgreSQL Activity Monitor

See what queries are currently running:

```bash
# Connect as postgres superuser
sudo -u postgres psql

# Run this query to see active connections and queries:
SELECT 
    pid,
    usename,
    application_name,
    client_addr,
    state,
    query,
    query_start
FROM pg_stat_activity
WHERE datname = 'alerts'
ORDER BY query_start DESC;
```

**What you'll see:**
- **pid**: Process ID of the connection
- **usename**: Which user is connected (eas_station, postgres, etc.)
- **application_name**: What's connected (gunicorn, psql, etc.)
- **state**: active, idle, idle in transaction
- **query**: The actual SQL being run
- **query_start**: When the query started

**To see blocked queries** (useful for debugging locks):

```sql
SELECT 
    blocked_locks.pid AS blocked_pid,
    blocked_activity.usename AS blocked_user,
    blocking_locks.pid AS blocking_pid,
    blocking_activity.usename AS blocking_user,
    blocked_activity.query AS blocked_statement,
    blocking_activity.query AS blocking_statement
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks 
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

If this returns no rows, nothing is blocked (good!).

**Type `\q` to exit psql.**

#### Method C: Use pgAdmin Query History

In pgAdmin (from Step 3.4):
1. Click **Tools** → **Server Activity**
2. Select your server
3. You'll see all active queries in real-time

**✅ Now zencoder.ai can monitor database activity as code runs!**

---

## Part 4: Viewing the Web Interface

Now let's set up access to the EAS Station web interface so zencoder.ai can see the UI, test changes, and verify functionality.

### Step 4.1: Understanding the Web Stack

**How the web interface works:**

```
Your Browser
    ↓ HTTPS (port 443)
Nginx (Reverse Proxy)
    ↓ HTTP (port 5000)
Gunicorn (WSGI Server)
    ↓ Python
Flask (Web Framework)
    ↓
EAS Station Application (app.py)
    ↓
PostgreSQL Database
```

**What this means:**
- Nginx handles HTTPS encryption and serves static files
- Gunicorn runs multiple Python workers for handling requests
- Flask routes requests to the right Python functions
- The app queries the database and returns HTML pages

### Step 4.2: Access the Web Interface from Your Browser

**Open your web browser** and navigate to:

```
https://YOUR_SERVER_IP
```

For example: `https://192.168.1.100`

**⚠️ Security Warning (Again):**

You'll see the SSL certificate warning again. Click **Advanced** → **Proceed** (it's your own server, so this is safe on your local network).

**What you should see:**

The EAS Station login page! You'll see:
- EAS Station logo/wordmark
- Login form (username and password fields)
- A clean, modern interface

### Step 4.3: Log In to the Interface

**Use the administrator account** you created during installation:

- **Username**: The username you chose during `install.sh`
- **Password**: The password you chose during `install.sh`

**Forgot your credentials?** Reset them on the server:

```bash
# On the server:
python /opt/eas-station/scripts/reset_admin_password.py
```

Follow the prompts to set a new password.

### Step 4.4: Explore the Interface

Once logged in, you should see:

**Dashboard (Home Page):**
- Recent alerts
- Service status indicators
- System health metrics
- Quick action buttons

**Main Navigation Menu:**

Explore these sections:
- **Alerts** - View all received alerts
- **Map** - Geographic visualization of alert coverage
- **Broadcast** - Manually trigger alert broadcasts
- **Audio** - Manage audio sources and monitoring
- **Configuration** - System settings
- **Admin** - User management, logs, diagnostics

**Try clicking around!** Get familiar with the interface.

### Step 4.5: Open Developer Tools (See What's Happening Under the Hood)

Let's see what the web interface is doing behind the scenes.

**In your browser, press F12** (or right-click anywhere and choose **Inspect**).

The browser's Developer Tools panel opens. You'll see several tabs:

#### Elements Tab
Shows the HTML structure of the page. You can:
- Click elements to inspect them
- Modify CSS styles live
- See what classes and IDs elements have

#### Console Tab  
Shows JavaScript output and errors. Look for:
- `console.log()` messages from the JavaScript code
- Errors (red text) - indicates problems
- Warnings (yellow text) - potential issues

**Try this:** Click around the EAS Station interface while watching the Console. You might see messages like:
```
[EAS Station] Fetching alert list...
[EAS Station] Received 42 alerts
[EAS Station] Updating dashboard...
```

#### Network Tab
**This is where zencoder.ai can see every web request!**

1. **Click the Network tab**
2. **Refresh the page** (press F5)
3. You'll see every request the page makes:

```
Name                  Status   Type       Size    Time
=====================================================
/                     200      document   45 KB   120ms
/static/css/style.css 200      stylesheet 12 KB   45ms
/api/alerts/recent    200      xhr        8 KB    230ms
/api/system/status    200      xhr        2 KB    15ms
```

**What this shows:**
- **Name**: What was requested (pages, API endpoints, files)
- **Status**: HTTP status code (200 = success, 404 = not found, 500 = server error)
- **Type**: What kind of file (HTML page, CSS, JavaScript, API response)
- **Size**: How big the response was
- **Time**: How long it took

**Click on any request** to see:
- **Headers**: Request/response headers
- **Preview**: Formatted view of the response
- **Response**: Raw response data
- **Timing**: Detailed breakdown of request time

**Example: Viewing an API Response**

1. Click on `/api/alerts/recent`
2. Click the **Preview** or **Response** tab
3. You'll see the JSON data:

```json
{
  "success": true,
  "alerts": [
    {
      "id": 1234,
      "event": "Severe Thunderstorm Warning",
      "headline": "Severe Thunderstorm Warning issued for...",
      "urgency": "Immediate",
      "severity": "Severe",
      "sent": "2025-01-15T10:30:00Z"
    },
    ...
  ]
}
```

This is the actual data the interface uses to display alerts!

#### Application Tab
Shows:
- **Local Storage**: Data saved in the browser
- **Session Storage**: Temporary session data
- **Cookies**: Authentication tokens, preferences

**Useful for debugging:**
- Check if user is logged in (look for session cookie)
- See theme preferences
- View cached data

### Step 4.6: Test Making Changes

Let's verify that code changes you (or zencoder.ai) make actually appear in the web interface.

**Step 1: Find a simple text to change**

In your IDE, open:
```
/opt/eas-station/webapp/templates/index.html
```

**Step 2: Find the welcome message** (around line 20-30):

```html
<h1>Welcome to EAS Station</h1>
```

**Step 3: Change it to:**

```html
<h1>Welcome to EAS Station - TEST MODE</h1>
```

**Step 4: Save the file**

Your IDE will automatically sync the file to the server (if configured correctly).

**Step 5: Restart the web service**

In your IDE terminal:
```bash
sudo systemctl restart eas-station-web.service
```

**Step 6: Refresh the browser** (F5)

You should now see "Welcome to EAS Station - TEST MODE"!

**✅ Success!** This proves:
- Your IDE edits files on the server
- Changes take effect after restarting the service
- The web interface reflects your changes

**Step 7: Change it back**

Edit the file again, remove "- TEST MODE", save, and restart the service.

### Step 4.7: View Service Logs While Using the Interface

This is incredibly useful for debugging - watch what the server does as you click through the interface.

**In your IDE terminal:**

```bash
# Watch web service logs in real-time
sudo journalctl -u eas-station-web.service -f
```

Now, **in your browser**, click on **Alerts** → **View All Alerts**.

**In the terminal**, you'll see log messages like:

```
Jan 15 10:45:23 raspberrypi gunicorn[1234]: [INFO] GET /alerts HTTP/1.1 200
Jan 15 10:45:23 raspberrypi gunicorn[1234]: [INFO] Query: SELECT * FROM cap_alerts ORDER BY sent DESC LIMIT 50
Jan 15 10:45:23 raspberrypi gunicorn[1234]: [INFO] Returned 42 alerts in 0.123s
```

**This shows you:**
- Which page was requested
- What database queries ran
- How long it took
- What the response was

Press `Ctrl+C` to stop watching the logs.

### Step 4.8: Take Screenshots for zencoder.ai

When working with zencoder.ai, you can take screenshots of the interface to share context.

**On Windows:**
- Press `Win + Shift + S` to capture a region
- Or use Snipping Tool

**On Mac:**
- Press `Cmd + Shift + 4` to capture a region
- Or press `Cmd + Shift + 3` for full screen

**On Linux:**
- Press `PrtScn` or use Screenshot tool

You can then paste these images into your conversation with zencoder.ai to show what you're seeing.

**✅ You can now view and test the web interface with full visibility into what's happening!**

---

## Part 5: Debugging with zencoder.ai - Full Visibility Into Failures

**The goal:** zencoder.ai should see when something breaks **immediately**, read the error logs automatically, and fix it - no more back-and-forth of "this doesn't work."

### Step 5.1: Understanding the Complete Visibility Model

**What we're setting up:**

```
Code Change Made
    ↓
Service Restarts Automatically
    ↓
Something Breaks? → Logs Show EXACTLY What Failed
    ↓
zencoder.ai SEES the error log automatically
    ↓
zencoder.ai Reads the Stack Trace
    ↓
zencoder.ai Identifies the Problem
    ↓
zencoder.ai Fixes the Code
    ↓
Service Restarts Again
    ↓
Verified: IT WORKS!
```

**No more:** "I tried it... it didn't work... let me copy the error... here's what it says..."

**Now:** zencoder.ai sees the failure, reads the logs, knows what to fix.

### Step 5.2: Real-Time Log Streaming in Your IDE

**Set up continuous log monitoring so zencoder.ai always sees what's happening.**

#### Option A: Split Terminal with Live Logs (Recommended)

**In VS Code:**

1. **Open a terminal**: Press `` Ctrl+` ``
2. **Split the terminal**: Click the split icon (looks like ⊞) in the terminal toolbar
3. **In the left terminal pane**, keep this running:
   ```bash
   # Monitor all EAS Station services continuously
   sudo journalctl -f -u 'eas-station*'
   ```
4. **In the right terminal pane**, you (or zencoder.ai) can execute commands

Now you have:
- **Left side**: Live log stream - every error, warning, info message appears here
- **Right side**: Command execution - run code, restart services, test things

**In PyCharm:**

1. Click **Terminal** tab at bottom
2. Click **+** icon to open a second terminal tab
3. **In Tab 1**: Keep the log stream running
   ```bash
   sudo journalctl -f -u 'eas-station*'
   ```
4. **In Tab 2**: Execute commands

#### Option B: Dedicated Log Window (Advanced)

Create a shell script that monitors logs with color highlighting:

```bash
# Create the monitoring script
nano ~/watch-eas-logs.sh
```

Paste this content:

```bash
#!/bin/bash
# EAS Station Real-Time Log Monitor
# Shows all services with color-coded severity levels

echo "========================================="
echo "  EAS STATION LIVE LOG MONITOR"
echo "  Press Ctrl+C to exit"
echo "========================================="
echo ""

# Follow all EAS Station service logs with colors
sudo journalctl -f -u 'eas-station*' | while read line; do
    # Color code based on log level
    if echo "$line" | grep -qi "ERROR\|CRITICAL\|FATAL"; then
        echo -e "\033[1;31m$line\033[0m"  # Red for errors
    elif echo "$line" | grep -qi "WARNING\|WARN"; then
        echo -e "\033[1;33m$line\033[0m"  # Yellow for warnings
    elif echo "$line" | grep -qi "INFO"; then
        echo -e "\033[1;32m$line\033[0m"  # Green for info
    elif echo "$line" | grep -qi "DEBUG"; then
        echo -e "\033[1;36m$line\033[0m"  # Cyan for debug
    else
        echo "$line"  # Normal for everything else
    fi
done
```

Make it executable:

```bash
chmod +x ~/watch-eas-logs.sh
```

Run it:

```bash
~/watch-eas-logs.sh
```

Now errors appear in **RED**, warnings in **YELLOW**, info in **GREEN**!

### Step 5.3: Automatic Error Detection and Reporting

Let's create a script that zencoder.ai can run to check if services are healthy:

```bash
# Create health check script
nano /opt/eas-station/check-health.sh
```

Paste this:

```bash
#!/bin/bash
# EAS Station Health Check
# Returns detailed status and recent errors

echo "======================================"
echo "EAS STATION HEALTH CHECK"
echo "Time: $(date)"
echo "======================================"
echo ""

# Check each service
for service in eas-station-web eas-station-audio eas-station-noaa-poller eas-station-ipaws-poller eas-station-eas eas-station-sdr eas-station-hardware; do
    echo "Checking: $service"
    
    # Get service status
    if systemctl is-active --quiet $service; then
        echo "  ✅ Status: RUNNING"
    else
        echo "  ❌ Status: FAILED/STOPPED"
        echo "  📋 Last 10 error lines:"
        sudo journalctl -u $service -n 10 --no-pager | grep -i error
    fi
    
    # Check for recent errors (last 5 minutes)
    error_count=$(sudo journalctl -u $service --since "5 minutes ago" --no-pager | grep -ci error)
    if [ $error_count -gt 0 ]; then
        echo "  ⚠️  Errors in last 5 minutes: $error_count"
        echo "  📋 Recent errors:"
        sudo journalctl -u $service --since "5 minutes ago" --no-pager | grep -i error | tail -5
    else
        echo "  ✅ No errors in last 5 minutes"
    fi
    
    echo ""
done

# Check database connectivity
echo "Checking: PostgreSQL Database"
if sudo -u eas-station psql -h localhost -U eas_station -d alerts -c "SELECT 1" > /dev/null 2>&1; then
    echo "  ✅ Database: CONNECTED"
else
    echo "  ❌ Database: CONNECTION FAILED"
fi
echo ""

# Check Redis
echo "Checking: Redis"
if redis-cli ping > /dev/null 2>&1; then
    echo "  ✅ Redis: CONNECTED"
else
    echo "  ❌ Redis: CONNECTION FAILED"
fi
echo ""

# Check disk space
echo "Checking: Disk Space"
df -h /opt/eas-station | tail -1 | awk '{print "  💾 Usage: " $5 " of " $2 " used (" $4 " free)"}'
echo ""

# Check memory
echo "Checking: Memory"
free -h | grep Mem | awk '{print "  🧠 RAM: " $3 " used / " $2 " total (" $4 " free)"}'
echo ""

echo "======================================"
echo "HEALTH CHECK COMPLETE"
echo "======================================"
```

Make it executable:

```bash
chmod +x /opt/eas-station/check-health.sh
```

**Now zencoder.ai can run this anytime:**

```bash
/opt/eas-station/check-health.sh
```

And immediately see:
- Which services are failing
- What errors occurred
- Database/Redis status
- System resources

### Step 5.4: Setting Up Breakpoint Debugging (So zencoder.ai Can Pause and Inspect)

**What we're doing:** Configuring the web service to support debugpy so zencoder.ai can:
- Set breakpoints in the code
- See exact variable values when errors occur
- Step through code line-by-line
- Understand complex logic flow

#### Configure VS Code for Debugging

If you haven't already, create `.vscode/launch.json`:

```bash
# Create .vscode directory
mkdir -p /opt/eas-station/.vscode

# Create launch configuration
nano /opt/eas-station/.vscode/launch.json
```

Paste this configuration:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Attach to Web Service",
            "type": "debugpy",
            "request": "attach",
            "connect": {
                "host": "localhost",
                "port": 5678
            },
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}",
                    "remoteRoot": "/opt/eas-station"
                }
            ],
            "justMyCode": false,
            "django": false,
            "jinja": true
        },
        {
            "name": "Attach to Audio Service",
            "type": "debugpy",
            "request": "attach",
            "connect": {
                "host": "localhost",
                "port": 5679
            },
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}",
                    "remoteRoot": "/opt/eas-station"
                }
            ],
            "justMyCode": false
        },
        {
            "name": "Attach to NOAA Poller",
            "type": "debugpy",
            "request": "attach",
            "connect": {
                "host": "localhost",
                "port": 5680
            },
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}",
                    "remoteRoot": "/opt/eas-station"
                }
            ],
            "justMyCode": false
        }
    ]
}
```

#### Configure PyCharm for Debugging

**In PyCharm:**

1. **Go to:** Run → Edit Configurations
2. **Click:** + → Python Debug Server
3. **Configure:**
   - **Name**: `EAS Web Service Debug`
   - **IDE host name**: `localhost`
   - **Port**: `5678`
   - **Path mappings**: 
     - Local: `/opt/eas-station` 
     - Remote: `/opt/eas-station`
4. **Click:** OK

**Repeat for other services** (Audio on port 5679, NOAA Poller on 5680, etc.)

### Step 5.5: Enable Debugging on the Web Service

Now let's configure the web service to accept debugger connections:

```bash
# Create systemd override for debugging
sudo systemctl edit eas-station-web.service
```

**Add this content:**

```ini
[Service]
# Override: Enable debugging with debugpy
# Clear the original command
ExecStart=

# Start with debugpy (listens on port 5678)
# NOTE: This waits for debugger to attach before starting
ExecStart=/opt/eas-station/venv/bin/python -m debugpy \
    --listen 0.0.0.0:5678 \
    /opt/eas-station/venv/bin/gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 1 \
    --threads 4 \
    --timeout 300 \
    --worker-class gthread \
    --log-level debug \
    --access-logfile /var/log/eas-station/web-access.log \
    --error-logfile /var/log/eas-station/web-error.log \
    app:app

# Increase timeout to allow for debugging pauses
TimeoutStartSec=300
```

**Save and apply:**

```bash
# Reload systemd
sudo systemctl daemon-reload

# Restart the service
sudo systemctl restart eas-station-web.service

# Verify it's listening for debugger
sudo netstat -tlnp | grep 5678
```

You should see:
```
tcp        0      0 0.0.0.0:5678            0.0.0.0:*               LISTEN      1234/python
```

### Step 5.6: How zencoder.ai Uses Debugging

**Scenario: Code breaks, zencoder.ai fixes it**

**1. zencoder.ai makes a code change** to fix a bug

**2. zencoder.ai restarts the service:**
```bash
sudo systemctl restart eas-station-web.service
```

**3. Service fails to start!** 

**4. zencoder.ai immediately checks logs:**
```bash
sudo journalctl -u eas-station-web.service -n 50 --no-pager
```

**5. Sees the error:**
```
Jan 15 11:23:45 raspberrypi gunicorn[5678]: Traceback (most recent call last):
Jan 15 11:23:45 raspberrypi gunicorn[5678]:   File "/opt/eas-station/app.py", line 234, in get_alerts
Jan 15 11:23:45 raspberrypi gunicorn[5678]:     alert_count = Alert.query.count()
Jan 15 11:23:45 raspberrypi gunicorn[5678]: AttributeError: 'NoneType' object has no attribute 'query'
```

**6. zencoder.ai understands:**
- The error is on line 234 of app.py
- The problem: `Alert` is `None` (should be a database model)
- Root cause: Import statement missing or wrong

**7. zencoder.ai fixes the code:**
```python
# Add missing import
from app_core.models import Alert
```

**8. zencoder.ai restarts and verifies:**
```bash
sudo systemctl restart eas-station-web.service
sudo systemctl status eas-station-web.service
```

**9. Sees:**
```
● eas-station-web.service - EAS Station Web Service
   Loaded: loaded
   Active: active (running)
```

**✅ Fixed! No back-and-forth needed.**

### Step 5.7: Complete Visibility Checklist

Make sure zencoder.ai has access to all these information sources:

**✅ Service Status:**
```bash
sudo systemctl status eas-station-web.service
```

**✅ Live Logs:**
```bash
sudo journalctl -f -u eas-station-web.service
```

**✅ Historical Logs:**
```bash
sudo journalctl -u eas-station-web.service --since "1 hour ago"
```

**✅ Error-Only Logs:**
```bash
sudo journalctl -u eas-station-web.service -p err -n 50
```

**✅ Python Stack Traces:**
```bash
sudo journalctl -u eas-station-web.service | grep -A 20 "Traceback"
```

**✅ Database Errors:**
```bash
sudo tail -100 /var/log/postgresql/postgresql-17-main.log | grep ERROR
```

**✅ Redis Errors:**
```bash
sudo journalctl -u redis-server --since "1 hour ago" | grep -i error
```

**✅ Nginx Errors:**
```bash
sudo tail -100 /var/log/nginx/error.log
```

**✅ System Resource Usage:**
```bash
# CPU and memory
top -bn1 | head -20

# Disk space
df -h

# Network connections
sudo netstat -tlnp
```

**✅ Process List:**
```bash
ps aux | grep -E "(python|gunicorn|redis|postgres|nginx)"
```

**✅ File Permissions (if permission errors occur):**
```bash
ls -la /opt/eas-station/
ls -la /var/log/eas-station/
```

**✅ Environment Variables:**
```bash
grep -v "^#" /opt/eas-station/.env | grep -v "^$"
```

**✅ Health Check:**
```bash
/opt/eas-station/check-health.sh
```

**With all these tools, zencoder.ai can:**
- See immediately when something breaks
- Read the exact error message
- Understand the root cause
- Fix the code
- Verify the fix worked
- **All without you having to manually copy/paste errors**

---

## Complete zencoder.ai Workflow Examples

Let's walk through real-world scenarios showing how zencoder.ai uses complete system visibility to develop and debug code without back-and-forth.

### Example 1: Fixing a Crash in the Web Service

**You say:** "zencoder.ai, the alert page is showing an error. Fix it."

**What zencoder.ai does (automatically):**

**Step 1: Check service status**
```bash
sudo systemctl status eas-station-web.service
```

**Sees:**
```
● eas-station-web.service - EAS Station Web Service
   Loaded: loaded
   Active: active (running) since 10:30:00
   ...recent errors in logs
```

**Step 2: Read recent logs**
```bash
sudo journalctl -u eas-station-web.service -n 100 --no-pager
```

**Finds the error:**
```
Jan 15 11:45:23 gunicorn[1234]: [ERROR] Exception on /alerts [GET]
Jan 15 11:45:23 gunicorn[1234]: Traceback (most recent call last):
Jan 15 11:45:23 gunicorn[1234]:   File "/opt/eas-station/webapp/routes.py", line 156, in get_alerts
Jan 15 11:45:23 gunicorn[1234]:     alerts = CAPAlert.query.filter(CAPAlert.status == 'Active').all()
Jan 15 11:45:23 gunicorn[1234]:   File "/opt/eas-station/venv/lib/python3.11/site-packages/sqlalchemy/orm/query.py", line 2887, in all
Jan 15 11:45:23 gunicorn[1234]:     return self._iter().all()
Jan 15 11:45:23 gunicorn[1234]: sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedColumn) column cap_alert.status does not exist
```

**Step 3: Understands the problem**
- Database table `cap_alert` doesn't have a `status` column
- Code is trying to filter by a non-existent column
- Need to check the actual database schema

**Step 4: Check actual database schema**
```bash
sudo -u eas-station psql -d alerts -c "\d cap_alerts"
```

**Sees:**
```
Column     |  Type   | Nullable
-----------+---------+----------
id         | integer | not null
event      | text    |
headline   | text    |
urgency    | text    |
severity   | text    |
sent       | timestamp |
expires    | timestamp |
...
(no status column!)
```

**Step 5: Examines the code**
```bash
cat /opt/eas-station/webapp/routes.py | grep -A 5 -B 5 "status == 'Active'"
```

**Step 6: Fixes the code**

Opens `/opt/eas-station/webapp/routes.py` and changes:

```python
# BEFORE (wrong):
alerts = CAPAlert.query.filter(CAPAlert.status == 'Active').all()

# AFTER (correct):
# Filter by unexpired alerts instead of non-existent status column
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
alerts = CAPAlert.query.filter(CAPAlert.expires > now).all()
```

**Step 7: Restarts the service**
```bash
sudo systemctl restart eas-station-web.service
```

**Step 8: Verifies the fix**
```bash
# Wait 2 seconds for service to start
sleep 2

# Check service status
sudo systemctl status eas-station-web.service

# Check recent logs for errors
sudo journalctl -u eas-station-web.service --since "10 seconds ago" | grep -i error
```

**Sees:** No errors! Service running!

**Step 9: Tests the endpoint**
```bash
# Test the alerts page
curl -s http://localhost:5000/alerts | grep -i error
```

**Sees:** No errors in the response!

**zencoder.ai reports:** "✅ Fixed! The issue was that the code was filtering by a `status` column that doesn't exist in the database. I changed it to filter by unexpired alerts using the `expires` timestamp column instead. The service is now running without errors."

**Total time:** ~30 seconds. No back-and-forth needed!

---

### Example 2: Database Query Performance Issue

**You say:** "zencoder.ai, the map page is really slow. Fix it."

**What zencoder.ai does:**

**Step 1: Enable query logging**
```bash
# Enable PostgreSQL query logging temporarily
sudo sed -i "s/log_statement = 'none'/log_statement = 'all'/" /etc/postgresql/*/main/postgresql.conf
sudo systemctl reload postgresql
```

**Step 2: Clear the log**
```bash
sudo truncate -s 0 /var/log/postgresql/postgresql-17-main.log
```

**Step 3: Test the slow page**
```bash
# Request the map page
curl -s http://localhost:5000/map > /dev/null

# Wait for query to complete
sleep 2
```

**Step 4: Check query log**
```bash
sudo tail -100 /var/log/postgresql/postgresql-17-main.log
```

**Finds the slow query:**
```
2025-01-15 11:50:23 [5678] eas_station@alerts LOG:  statement: 
    SELECT counties.*, ST_AsGeoJSON(counties.geom) as geometry
    FROM counties
    WHERE ST_Intersects(counties.geom, ST_GeomFromGeoJSON('...'))
2025-01-15 11:50:35 [5678] eas_station@alerts LOG:  duration: 12453.789 ms
```

**Analyzes:** Query took 12 seconds! The `ST_Intersects` is slow because there's no spatial index.

**Step 5: Check for indexes**
```bash
sudo -u eas-station psql -d alerts -c "\di counties*"
```

**Sees:** No spatial index on the `geom` column!

**Step 6: Creates the index**
```bash
sudo -u eas-station psql -d alerts -c "CREATE INDEX idx_counties_geom ON counties USING GIST(geom);"
```

**Sees:**
```
CREATE INDEX
```

**Step 7: Tests again**
```bash
# Clear log
sudo truncate -s 0 /var/log/postgresql/postgresql-17-main.log

# Test the page again
curl -s http://localhost:5000/map > /dev/null

# Check query time
sudo tail -100 /var/log/postgresql/postgresql-17-main.log | grep duration
```

**Sees:**
```
2025-01-15 11:52:10 [5678] eas_station@alerts LOG:  duration: 127.456 ms
```

**127ms instead of 12 seconds!** 100x faster!

**Step 8: Disable query logging**
```bash
sudo sed -i "s/log_statement = 'all'/log_statement = 'none'/" /etc/postgresql/*/main/postgresql.conf
sudo systemctl reload postgresql
```

**zencoder.ai reports:** "✅ Fixed! The map page was slow because the `counties` table didn't have a spatial index on the geometry column. I added a GIST index which reduced query time from 12 seconds to 127ms - a 100x improvement!"

---

### Example 3: Redis Connection Issues

**You say:** "zencoder.ai, the audio service shows 'No metrics available'. Fix it."

**What zencoder.ai does:**

**Step 1: Check the audio service**
```bash
sudo systemctl status eas-station-audio.service
```

**Sees:** Service is running

**Step 2: Check logs**
```bash
sudo journalctl -u eas-station-audio.service -n 50 --no-pager
```

**Finds:**
```
Jan 15 12:00:15 audio_service[9876]: [WARNING] Failed to publish metrics to Redis: Connection refused
Jan 15 12:00:15 audio_service[9876]: [ERROR] redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379
```

**Step 3: Check Redis status**
```bash
sudo systemctl status redis-server
```

**Sees:**
```
● redis-server.service - Advanced key-value store
   Loaded: loaded
   Active: inactive (dead)
```

Redis isn't running!

**Step 4: Start Redis**
```bash
sudo systemctl start redis-server
```

**Step 5: Verify it's working**
```bash
redis-cli ping
```

**Sees:** `PONG`

**Step 6: Restart audio service**
```bash
sudo systemctl restart eas-station-audio.service
```

**Step 7: Check logs again**
```bash
sudo journalctl -u eas-station-audio.service --since "10 seconds ago"
```

**Sees:**
```
Jan 15 12:01:30 audio_service[9999]: [INFO] Connected to Redis successfully
Jan 15 12:01:31 audio_service[9999]: [INFO] Published metrics: {"status": "running", "level": -23.4}
```

**Step 8: Verify metrics are available**
```bash
redis-cli GET eas-audio-metrics
```

**Sees:**
```json
{"service":"audio","status":"running","level":-23.4,"timestamp":"2025-01-15T12:01:31Z"}
```

**Step 9: Test the web page**
```bash
curl -s http://localhost:5000/api/audio/metrics
```

**Sees:**
```json
{"success": true, "metrics": {"level": -23.4, "status": "running"}}
```

**Step 10: Enable Redis to start on boot**
```bash
sudo systemctl enable redis-server
```

**zencoder.ai reports:** "✅ Fixed! The audio service couldn't publish metrics because Redis wasn't running. I started Redis, restarted the audio service, and enabled Redis to start automatically on boot. The metrics are now available."

---

### Example 4: Frontend JavaScript Error

**You say:** "zencoder.ai, the dashboard isn't updating. Fix it."

**What zencoder.ai does:**

**Step 1: Check browser console logs**

zencoder.ai asks you to open the browser developer console (F12) and copy any errors, or views the page source to understand the JavaScript:

```bash
# View the dashboard JavaScript
cat /opt/eas-station/static/js/dashboard.js | grep -A 10 "updateDashboard"
```

**Sees:**
```javascript
function updateDashboard() {
    fetch('/api/dashboard/data')
        .then(response => response.json())
        .then(data => {
            // Update alert count
            document.getElementById('alert-count').innerText = data.count;
        })
        .catch(error => console.error('Error:', error));
}
```

**Step 2: Test the API endpoint**
```bash
curl -s http://localhost:5000/api/dashboard/data
```

**Sees:**
```json
{"error": "Internal server error"}
```

**Step 3: Check web service logs**
```bash
sudo journalctl -u eas-station-web.service -n 50 | grep "/api/dashboard/data"
```

**Finds:**
```
Jan 15 12:30:45 gunicorn[3456]: [ERROR] Exception in /api/dashboard/data
Jan 15 12:30:45 gunicorn[3456]: KeyError: 'count'
```

**Step 4: Examines the API code**
```bash
cat /opt/eas-station/webapp/api/dashboard.py | grep -A 20 "def get_dashboard_data"
```

**Sees:**
```python
@dashboard_bp.route('/data')
def get_dashboard_data():
    alerts = CAPAlert.query.filter(CAPAlert.expires > datetime.now(timezone.utc)).all()
    return jsonify({
        'alert_count': len(alerts)  # ← Key is 'alert_count' not 'count'!
    })
```

**Step 5: Fixes the inconsistency**

Either change the API to return `count`, or change the JavaScript to use `alert_count`. Let's fix the JavaScript:

```javascript
// BEFORE:
document.getElementById('alert-count').innerText = data.count;

// AFTER:
document.getElementById('alert-count').innerText = data.alert_count;
```

**Step 6: Test the fix**
```bash
# Restart web service (to reload JavaScript changes served through Flask)
sudo systemctl restart eas-station-web.service

# Test API again
curl -s http://localhost:5000/api/dashboard/data
```

**Sees:**
```json
{"alert_count": 42}
```

Works!

**zencoder.ai reports:** "✅ Fixed! The dashboard JavaScript was trying to access `data.count`, but the API returns `data.alert_count`. I updated the JavaScript to use the correct property name. The dashboard should now update properly."

---

### Key Takeaways from These Examples

**What enables zencoder.ai to work autonomously:**

1. **Full log access** - Sees exact error messages immediately
2. **Service control** - Can restart services to test fixes
3. **Database access** - Can check schema and data
4. **Redis access** - Can monitor real-time communication
5. **System monitoring** - Can check resource usage, network, processes
6. **Code access** - Can read and modify files
7. **Testing tools** - Can test endpoints, query database, check responses

**No more:**
- ❌ "What does the error say?"
- ❌ "Can you check the logs?"
- ❌ "Did that fix it?"
- ❌ "What about now?"

**Now:**
- ✅ zencoder.ai sees the error
- ✅ zencoder.ai understands the cause
- ✅ zencoder.ai fixes the code
- ✅ zencoder.ai verifies it works
- ✅ zencoder.ai reports the solution

**That's complete visibility!**

---

This method lets you quickly test debugging without modifying systemd services.

**Example: Debug the Web Service**

1. **Stop the systemd service**:
```bash
sudo systemctl stop eas-station-web.service
```

2. **Start the service manually with debugpy** (as the service user):
```bash
# Run as the eas-station user with debugpy enabled
sudo -u eas-station /opt/eas-station/venv/bin/python -m debugpy \
    --listen 0.0.0.0:5678 \
    --wait-for-client \
    /opt/eas-station/app.py
```

3. **Attach your IDE debugger**:
   - In VS Code: Press `F5` and select "Attach to Web Service"
   - In PyCharm: Click the debug icon (green bug)

4. **Set breakpoints and debug** as normal!

5. **When done**, stop the manual process (`Ctrl+C`) and restart the systemd service:
```bash
sudo systemctl start eas-station-web.service
```

**Example: Debug the Audio Service**

```bash
# Stop the service
sudo systemctl stop eas-station-audio.service

# Run with debugpy on port 5679
sudo -u eas-station /opt/eas-station/venv/bin/python -m debugpy \
    --listen 0.0.0.0:5679 \
    --wait-for-client \
    /opt/eas-station/eas_monitoring_service.py

# Attach debugger on port 5679, then restart when done:
sudo systemctl start eas-station-audio.service
```

### Method 2: Persistent Debug Mode (For Long-Term Development)

This method modifies the systemd service file to always run with debugpy enabled.

**Example: Enable debugging for Web Service**

1. **Create a systemd override file**:
```bash
sudo systemctl edit eas-station-web.service
```

2. **Add this content** (this opens an editor):
```ini
[Service]
# Clear the original ExecStart
ExecStart=

# Replace with debugpy-enabled start command
# ⚠️ SECURITY WARNING: Using 0.0.0.0 exposes debug port to all network interfaces
# - Debug ports allow ARBITRARY CODE EXECUTION - attackers can run any Python code
# - Only use 0.0.0.0 on isolated/trusted networks (never public internet)
# - For local debugging only, use 127.0.0.1:5678 instead
# - For remote debugging, use SSH port forwarding (see below) to keep ports local
ExecStart=/opt/eas-station/venv/bin/python -m debugpy \
    --listen 0.0.0.0:5678 \
    /opt/eas-station/venv/bin/gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --timeout 300 \
    --worker-class gevent \
    --worker-connections 1000 \
    --log-level info \
    --access-logfile /var/log/eas-station/web-access.log \
    --error-logfile /var/log/eas-station/web-error.log \
    app:app
```

3. **Save and exit**, then reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart eas-station-web.service
```

4. **Verify debugpy is listening**:
```bash
# Check service status
sudo systemctl status eas-station-web.service

# Verify port 5678 is listening
sudo netstat -tlnp | grep 5678
```

5. **Attach your debugger** and start debugging!

6. **To revert** to normal mode (disable debugging):
```bash
# Remove the override
sudo systemctl revert eas-station-web.service

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart eas-station-web.service
```

### Method 3: Direct Code Modification (For app.py)

For the Flask web application, you can add debugpy directly to `app.py`:

1. **Edit app.py**:
```bash
# Via SSH or your IDE:
nano /opt/eas-station/app.py
```

2. **Add at the very beginning** (before imports):
```python
# Debug support - REMOVE IN PRODUCTION
import os
if os.environ.get('ENABLE_DEBUGPY', 'false').lower() == 'true':
    import debugpy
    debugpy.listen(("0.0.0.0", 5678))
    print("⚠️ debugpy listening on port 5678 - WAITING FOR DEBUGGER")
    # Remove wait-for-client in production, or the app won't start until debugger attaches
    # debugpy.wait_for_client()
    print("✓ Debugger attached!")
```

3. **Enable via environment variable**:
```bash
# Edit .env
sudo nano /opt/eas-station/.env

# Add this line:
ENABLE_DEBUGPY=true
```

4. **Restart the web service**:
```bash
sudo systemctl restart eas-station-web.service
```

5. **Attach debugger** from your IDE

6. **IMPORTANT**: Before committing to Git, either:
   - Remove the debugpy code entirely, OR
   - Set `ENABLE_DEBUGPY=false` in `.env` and never commit with it enabled

### Port Assignments for Debugging

Use different ports for each service to debug multiple services simultaneously:

| Service | Main Process | Debug Port | Launch Command |
|---------|-------------|------------|----------------|
| **Web** | `app.py` → gunicorn | `5678` | See Method 1 above |
| **Audio** | `eas_monitoring_service.py` | `5679` | See audio example above |
| **NOAA Poller** | Poller script | `5680` | `debugpy --listen 0.0.0.0:5680 ...` |
| **IPAWS Poller** | Poller script | `5681` | `debugpy --listen 0.0.0.0:5681 ...` |
| **EAS** | EAS service | `5682` | `debugpy --listen 0.0.0.0:5682 ...` |
| **SDR** | SDR service | `5683` | `debugpy --listen 0.0.0.0:5683 ...` |
| **Hardware** | Hardware service | `5684` | `debugpy --listen 0.0.0.0:5684 ...` |

### Firewall Configuration for Remote Debugging

If debugging from a remote machine (not localhost), ensure the debug ports are accessible:

```bash
# Allow debugpy ports through firewall
sudo ufw allow 5678/tcp comment 'debugpy - web service'
sudo ufw allow 5679/tcp comment 'debugpy - audio service'
# ... add more as needed

# Check firewall status
sudo ufw status
```

**⚠️ CRITICAL SECURITY WARNING**: 
- **Debug ports allow ARBITRARY CODE EXECUTION** - anyone who can connect can run any Python code on your server
- **NEVER expose debug ports to the public internet**
- Only enable on isolated/trusted networks (e.g., home LAN, private VPN)
- **Preferred approach**: Use SSH port forwarding (see below) instead of opening firewall ports
- If you must open firewall ports, restrict by source IP using ufw: `sudo ufw allow from 192.168.1.50 to any port 5678`

### SSH Port Forwarding (Secure Remote Debugging)

**RECOMMENDED**: Instead of opening firewall ports, use SSH tunneling:

```bash
# From your local machine, forward debug port 5678 through SSH:
ssh -L 5678:localhost:5678 eas-station@YOUR_SERVER_IP

# Now attach debugger to localhost:5678 on YOUR machine
# The connection is encrypted through SSH
```

---

## Using with AI Coding Agents (ZenCoder, etc.)

AI coding agents like ZenCoder work best when they can see your code, run it, and observe failures in real-time. Here's how to integrate them with your EAS Station development environment.

### Why This Setup is Perfect for AI Agents

✅ **Real-time code access** - Agent sees all files via SSH
✅ **Immediate execution** - Code changes run instantly on server
✅ **Full debugging** - Agent can use debugpy to inspect state
✅ **Database access** - Agent can query/modify the database
✅ **Log streaming** - Agent can watch systemd logs in real-time
✅ **Hardware testing** - Agent can test with actual GPIO/SDR/audio devices

### Setting Up ZenCoder with PyCharm

1. **Install ZenCoder extension** in PyCharm:
   - Go to **Settings** → **Plugins** → **Marketplace**
   - Search for "ZenCoder" and install
   - Restart PyCharm

2. **Configure ZenCoder** for remote development:
   - ZenCoder automatically uses your project's Python interpreter
   - Since you've set up SSH Remote Interpreter, ZenCoder will execute code on the server
   - No additional configuration needed!

3. **Grant ZenCoder access to debugging**:
   - Enable debugpy for the service you're working on (see above)
   - ZenCoder can attach to debugpy sessions to inspect variables
   - Share your launch.json configuration with ZenCoder

### Workflow Example: Using ZenCoder to Fix a Bug

**Scenario**: You found a bug in alert processing. Let ZenCoder help!

1. **Describe the problem to ZenCoder**:
   ```
   "The NOAA poller is crashing when processing alerts with invalid GeoJSON.
   Check the logs and fix the issue."
   ```

2. **ZenCoder can**:
   - Read the systemd logs: `journalctl -u eas-station-noaa-poller.service -n 100`
   - View the source code: `/opt/eas-station/app_core/noaa_poller.py`
   - Check the database: Query the `cap_alerts` table via psql or Python
   - Test the fix: Modify the code and restart the service
   - Verify: Check logs again to confirm the fix works

3. **ZenCoder sees changes immediately**:
   - Code edits sync to `/opt/eas-station/` via PyCharm
   - Service restarts pick up changes instantly
   - Logs show the results in real-time

4. **ZenCoder can use the debugger**:
   - Set breakpoints in the code
   - Attach to debugpy session
   - Inspect variables when the crash occurs
   - Trace the execution flow

### Example: ZenCoder Database Queries

ZenCoder can query the database directly to understand data issues:

```python
# ZenCoder can run this in the Python console (via PyCharm or SSH):
import psycopg2
conn = psycopg2.connect(
    host='localhost',
    port=5432,
    database='alerts',
    user='eas_station',
    password='<from .env>'
)
cur = conn.cursor()
cur.execute("SELECT id, event, message_type, status FROM cap_alerts WHERE status = 'Error' LIMIT 10;")
for row in cur.fetchall():
    print(row)
```

### Example: ZenCoder Log Analysis

```bash
# ZenCoder can run systemctl commands via SSH:
sudo journalctl -u eas-station-noaa-poller.service --since "1 hour ago" | grep ERROR
```

### Best Practices for AI Agent Development

1. **Give context**: Share error logs, stack traces, and database states with the agent
2. **Use descriptive file names**: AI agents parse better with clear naming
3. **Keep services running**: Don't stop all services - isolate the one you're debugging
4. **Test incrementally**: Let the agent make small changes, test, then iterate
5. **Review AI changes**: Always review and test before committing
6. **Use version control**: Commit working states frequently so you can rollback AI mistakes

### Permissions for AI Agents

ZenCoder runs as your user via PyCharm. For system commands (like `systemctl`), configure sudo access:

```bash
# On the server, edit sudoers for the eas-station user (if needed):
sudo visudo

# Add (adjust as needed for security - these are minimal permissions):
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl restart eas-station-*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl stop eas-station-*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl start eas-station-*
eas-station ALL=(ALL) NOPASSWD: /bin/systemctl status eas-station-*
# Restrict journalctl to EAS Station services only
eas-station ALL=(ALL) NOPASSWD: /bin/journalctl -u eas-station-*
```

**⚠️ Security Notes**: 
- Only grant minimal necessary permissions
- The above restricts systemctl to eas-station-* services only
- journalctl is restricted to eas-station-* units to prevent reading sensitive system logs
- Consider using `sudo -v` to cache credentials instead for even tighter security

---

## Development Workflow

### Daily Workflow

1. **Connect via SSH** (your IDE handles this automatically):
```bash
# VS Code: Use Remote-SSH extension (already connected)
# PyCharm: Uses SSH interpreter (already connected)

# Or manual SSH for command-line work:
ssh eas-station@YOUR_SERVER_IP
```

2. **Check service status**:
```bash
# View all EAS Station services
sudo systemctl status eas-station.target

# Check specific service
sudo systemctl status eas-station-web.service

# View recent logs
sudo journalctl -u eas-station-web.service -f
```

3. **Edit code in your IDE**:
   - Edit files in VS Code or PyCharm
   - Changes sync to `/opt/eas-station/` automatically (PyCharm deployment)
   - Or edit directly via SSH (changes are immediate)

4. **Test changes**:
```bash
# Restart the service you modified
sudo systemctl restart eas-station-web.service

# Watch the logs for errors
sudo journalctl -u eas-station-web.service -f

# Test via web browser
# Navigate to https://YOUR_SERVER_IP
```

5. **Debug with breakpoints**:
   - Enable debugpy for the service (see [Debugging Individual Services](#debugging-individual-services))
   - Set breakpoints in your IDE
   - Attach debugger
   - Trigger the code path (web request, timer, etc.)
   - Step through code, inspect variables

6. **Iterate quickly**:
   - Make changes
   - Restart service: `sudo systemctl restart eas-station-web.service`
   - Test
   - Repeat

7. **Commit only working code**:
```bash
# On the server or via your IDE's Git integration:
git status
git diff
git add <specific-files>
git commit -m "Fix: Clear description of what you fixed"
git push origin <branch-name>
```

### Rapid Development Tips

**Tip 1: Auto-reload Flask app** (for web service only)

During development, you can run the Flask app in debug mode for automatic reloading:

```bash
# Stop the systemd service
sudo systemctl stop eas-station-web.service

# Run Flask dev server manually (as eas-station user)
sudo -u eas-station bash -c 'cd /opt/eas-station && source venv/bin/activate && FLASK_ENV=development python app.py'

# Flask will auto-reload when you save files
# Press Ctrl+C to stop, then restart the systemd service:
sudo systemctl start eas-station-web.service
```

**Tip 2: Watch logs in real-time**

```bash
# Watch all EAS Station services
sudo journalctl -u 'eas-station*' -f

# Watch specific service
sudo journalctl -u eas-station-web.service -f

# Watch with grep filter
sudo journalctl -u eas-station-web.service -f | grep ERROR
```

**Tip 3: Test database changes**

```bash
# Open psql as eas_station user
sudo -u postgres psql -d alerts

# Or from your IDE's database tools
# (see Database Configuration section)
```

### Understanding Service Dependencies

```bash
# View service dependency tree
systemd-analyze dot 'eas-station*' | dot -Tpng > /tmp/eas-services.png

# Check which services depend on which
sudo systemctl list-dependencies eas-station.target
```

**Service startup order**:
1. PostgreSQL, Redis (system services)
2. eas-station-web.service
3. eas-station-audio.service, eas-station-sdr.service
4. eas-station-*-poller.service (depends on web for database)
5. eas-station-eas.service, eas-station-hardware.service

**What this means for debugging**:
- If you restart the web service, pollers should still work (they reconnect)
- If you restart PostgreSQL, you need to restart all EAS Station services
- If you restart Redis, restart audio/poller services

### Testing on Real Hardware

**Advantages of bare metal development**:
- Test with actual GPIO pins (if on Raspberry Pi)
- Test with real audio devices (USB sound cards, SDR)
- Test with actual network performance
- Test with real-time constraints

**Example: Test SDR integration**

```bash
# Stop the SDR service
sudo systemctl stop eas-station-sdr.service

# Run manually with verbose logging
sudo -u eas-station /opt/eas-station/venv/bin/python \
    /opt/eas-station/scripts/debug/test_sdr_direct.py

# Or run with debugpy for debugging:
sudo -u eas-station /opt/eas-station/venv/bin/python -m debugpy \
    --listen 0.0.0.0:5683 --wait-for-client \
    /opt/eas-station/scripts/debug/test_sdr_direct.py
```

### Working with Multiple Developers

**Scenario**: Multiple developers on the same server

1. **Use separate Git branches**:
```bash
# Developer 1
git checkout -b feature/new-alert-parser

# Developer 2
git checkout -b feature/led-sign-update
```

2. **Each developer debugs their own service**:
   - Dev 1 debugs poller service on port 5680
   - Dev 2 debugs hardware service on port 5684

3. **Use systemd service overrides per developer**:
```bash
# Developer 1 creates override for poller:
sudo systemctl edit eas-station-noaa-poller.service
# (add debugpy)

# Developer 2 creates override for hardware:
sudo systemctl edit eas-station-hardware.service
# (add debugpy on different port)
```

4. **Communicate and merge**:
   - Test changes independently
   - Merge to main branch when working
   - Let CI/CD run tests

---

## Troubleshooting

### Problem: "Connection Refused" When Debugging

**Solution**:
```bash
# Check if debugpy is listening on the port
sudo netstat -tlnp | grep 5678

# Check service status
sudo systemctl status eas-station-web.service

# View service logs for errors
sudo journalctl -u eas-station-web.service -n 50

# Restart the service
sudo systemctl restart eas-station-web.service
```

---

### Problem: PyCharm/VS Code Can't Connect via SSH

**Solution**:
```bash
# On the server, check SSH status
sudo systemctl status ssh

# If not running, start it
sudo systemctl start ssh

# Test from your computer
ssh eas-station@192.168.1.100
```

---

### Problem: "Can't connect to database"

**Cause**: Wrong hostname in `.env` or network/firewall issue.

**Solution**:

1. **Check your `.env` file has the correct `POSTGRES_HOST`**:

```bash
# On the server, check the config:
sudo grep POSTGRES_HOST /opt/eas-station/.env

# Should be:
POSTGRES_HOST=localhost  # For local PostgreSQL on the server
```

2. **For remote desktop tools**, verify network connectivity:

```powershell
# Test from Windows PowerShell:
Test-NetConnection -ComputerName 192.168.1.100 -Port 5432
```

```bash
# Or from Linux/Mac:
nc -zv 192.168.1.100 5432
```

If this fails, check the server's firewall:
```bash
# On the server:
sudo ufw allow 5432/tcp
sudo ufw status

# Verify the port is listening:
sudo netstat -tlnp | grep 5432
```

3. **Restart the service** after changing `.env`:
```bash
sudo systemctl restart eas-station-web.service
```

---

### Problem: "Can't connect to database from remote tools"

**Cause**: Firewall blocking port 5432 or PostgreSQL not listening on external interface.

**Solution**:

1. **Configure PostgreSQL to accept remote connections**:
```bash
# ⚠️ SECURITY WARNING: The following configuration allows remote database access
# Only do this on trusted networks or use SSH tunneling instead (see below)

# Edit postgresql.conf
sudo nano /etc/postgresql/*/main/postgresql.conf

# Find and change (for all IPs - less secure):
listen_addresses = '*'
# OR for specific IP only (more secure):
listen_addresses = 'localhost,192.168.1.100'

# Edit pg_hba.conf to allow your machine
sudo nano /etc/postgresql/*/main/pg_hba.conf

# Add this line (replace with your specific network/IP for better security):
host    alerts    eas_station    192.168.1.0/24    scram-sha-256
# OR for a single IP (more secure):
# host    alerts    eas_station    192.168.1.50/32    scram-sha-256

# Restart PostgreSQL
sudo systemctl restart postgresql
```

**Security Best Practice**: Instead of exposing PostgreSQL to the network, use SSH port forwarding:
```bash
# From your local machine, create SSH tunnel:
ssh -L 5432:localhost:5432 eas-station@YOUR_SERVER_IP

# Now connect your database tools to localhost:5432 on your machine
# The connection is encrypted through SSH and no firewall changes needed
```

2. **Check server's firewall**:
```bash
# On the server:
sudo ufw allow 5432/tcp

# If ufw is not active:
sudo ufw status
```

3. **Test from your local machine**:
```powershell
# Windows PowerShell:
Test-NetConnection -ComputerName 192.168.1.100 -Port 5432

# Should show: TcpTestSucceeded : True
```

```bash
# On the server:
sudo netstat -tlnp | grep 5432

# Should show: 0.0.0.0:5432 (not 127.0.0.1:5432)
```

---

### Problem: Code Changes Not Appearing

**Solution**:

1. **Check IDE sync status** (bottom of window in PyCharm)
2. **Manually trigger sync**: **Tools** → **Deployment** → **Sync with Deployed to...**
3. **Restart the service**:
```bash
sudo systemctl restart eas-station-web.service
```

4. **Verify file was actually updated**:
```bash
# SSH to server and check file timestamp
ls -l /opt/eas-station/app.py

# Or view the file:
tail -20 /opt/eas-station/app.py
```

---

### Problem: "Permission Denied" on /dev/snd or GPIO

**Solution**:
```bash
# Add the eas-station user to necessary groups
sudo usermod -aG audio,gpio,dialout eas-station

# Restart the services for group changes to take effect
sudo systemctl restart eas-station.target

# Verify group membership
sudo -u eas-station groups
```

---

### Problem: debugpy Won't Start - "Address already in use"

**Cause**: Another process is using the debug port (5678).

**Solution**:
```bash
# Find what's using the port
sudo netstat -tlnp | grep 5678

# Kill the process (replace PID with actual PID)
sudo kill <PID>

# Or if it's another eas-station service:
sudo systemctl restart eas-station-web.service
```

---

### Problem: Service Crashes After Code Changes

**Cause**: Syntax error or runtime exception in your code.

**Solution**:
```bash
# View the service logs to find the error
sudo journalctl -u eas-station-web.service -n 100

# Common issues:
# - Python syntax errors
# - Import errors (missing dependencies)
# - Database migration needed
# - Missing environment variables

# Test the code manually before restarting service:
sudo -u eas-station /opt/eas-station/venv/bin/python -c "import app"
```

---

### Problem: Changes Work Locally But Break in Production

**Cause**: Different environment variables or database state.

**Solution**:
```bash
# Compare .env files
diff /opt/eas-station/.env /opt/eas-station/.env.example

# Check database migrations
cd /opt/eas-station
sudo -u eas-station /opt/eas-station/venv/bin/alembic current
sudo -u eas-station /opt/eas-station/venv/bin/alembic upgrade head

# Ensure dependencies are installed
sudo -u eas-station /opt/eas-station/venv/bin/pip install -r requirements.txt

# Restart all services
sudo systemctl restart eas-station.target
```

---
---

## Best Practices

### DO ✅

- **Test locally first**: Always debug on the server before pushing to GitHub
- **Use breakpoints**: Don't just add print statements - use real debugging
- **Commit often**: When something works, commit it immediately
- **Write descriptive commits**: "Fix: Describe what you fixed" not "fixed stuff"
- **Use systemd service overrides**: Don't modify the main service files in `/etc/systemd/system/`
- **Clean up debug code**: Remove or disable debugpy before committing
- **Test with real hardware**: Take advantage of bare metal for GPIO/SDR/audio testing
- **Watch logs**: Use `journalctl -f` to see real-time feedback
- **Use separate branches**: Create feature branches for AI agent experiments

### DON'T ❌

- **Don't push untested code**: Test it on the server first!
- **Don't commit broken code**: Fix it first, then commit
- **Don't commit debug configurations**: Keep those in systemd overrides
- **Don't commit secrets**: Check for passwords/API keys before committing (use `.env`)
- **Don't use `git add .`**: Add specific files only
- **Don't leave debugpy enabled**: Disable debug mode for production
- **Don't modify production services directly**: Use `systemctl edit` for overrides
- **Don't run services as root**: Always use `sudo -u eas-station` for testing

---

## Debugging Specific Services

### Audio Service

```bash
# View logs in real-time
sudo journalctl -u eas-station-audio.service -f

# Restart just the audio service
sudo systemctl restart eas-station-audio.service

# Stop and run manually with debug output
sudo systemctl stop eas-station-audio.service
sudo -u eas-station /opt/eas-station/venv/bin/python eas_monitoring_service.py
```

### Poller Service

```bash
# Check NOAA poller logs
sudo journalctl -u eas-station-noaa-poller.service -n 100

# Check IPAWS poller logs
sudo journalctl -u eas-station-ipaws-poller.service -n 100

# Run poller manually with debug output
sudo systemctl stop eas-station-noaa-poller.service
sudo -u eas-station /opt/eas-station/venv/bin/python -c "from app_core.noaa_poller import poll_noaa; poll_noaa()"
```

### Hardware Service

```bash
# View hardware service logs
sudo journalctl -u eas-station-hardware.service -f

# Test GPIO without running the service
sudo systemctl stop eas-station-hardware.service
sudo -u eas-station /opt/eas-station/venv/bin/python -c "from app_core import hardware; hardware.test_gpio()"
```

---

## Keeping Your Git History Clean

### Use .gitignore

These files should NOT be committed (already in `.gitignore`):

```gitignore
*.log
__pycache__/
.env
dev_data/
```

### Check Before Committing

```bash
# Always check what you're about to commit
git status
git diff

# Only add specific files
git add app.py app_core/alerts.py

# NOT this (adds everything):
# git add .
```

### Write Good Commit Messages

❌ Bad:
```
git commit -m "fixed stuff"
git commit -m "update"
```

✅ Good:
```
git commit -m "Fix: Audio service crash when USB device disconnects"
git commit -m "Add: Retry logic for failed IPAWS poll requests"
git commit -m "Improve: Alert deduplication performance"
```

---

## Quick Reference

### Daily Commands

```bash
# Connect to server
ssh eas-station@192.168.1.100

# Check all services status
sudo systemctl status eas-station.target

# Check specific service
sudo systemctl status eas-station-web.service

# Restart a service after code changes
sudo systemctl restart eas-station-web.service

# Watch logs in real-time
sudo journalctl -u eas-station-web.service -f

# Stop all services
sudo systemctl stop eas-station.target

# Start all services
sudo systemctl start eas-station.target

# Enable debugpy for a service (temporary)
sudo systemctl stop eas-station-web.service
sudo -u eas-station /opt/eas-station/venv/bin/python -m debugpy \
    --listen 0.0.0.0:5678 --wait-for-client /opt/eas-station/app.py
```

### systemd Service Management

```bash
# List all EAS Station services
sudo systemctl list-units 'eas-station*'

# Edit a service (creates override)
sudo systemctl edit eas-station-web.service

# Revert service to default (remove override)
sudo systemctl revert eas-station-web.service

# Reload systemd after manual edits
sudo systemctl daemon-reload

# View service dependencies
sudo systemctl list-dependencies eas-station.target
```

### Database Quick Access

```bash
# Connect to PostgreSQL as eas_station user
sudo -u postgres psql -d alerts

# Or with password auth:
psql -h localhost -U eas_station -d alerts

# Get database password
sudo grep POSTGRES_PASSWORD /opt/eas-station/.env

# pgAdmin web interface
# Navigate to: https://YOUR_SERVER_IP/pgadmin4
```

### IDE Shortcuts

**VS Code**:
- **Set Breakpoint**: Click left margin or `F9`
- **Start Debugging**: `F5`
- **Step Over**: `F10`
- **Step Into**: `F11`
- **Continue**: `F5`
- **Stop Debugging**: `Shift+F5`

**PyCharm**:
- **Set Breakpoint**: Click left margin or `Ctrl+F8` / `Cmd+F8`
- **Start Debugging**: `Shift+F9`
- **Step Over**: `F8`
- **Step Into**: `F7`
- **Resume**: `F9`
- **Stop Debugging**: `Ctrl+F2` / `Cmd+F2`

---

## Summary

You now have a complete development environment where you can:

1. ✅ Edit code in PyCharm/VS Code on your local machine via SSH
2. ✅ Run and debug on real Linux server / Raspberry Pi hardware
3. ✅ Access the database remotely (pgAdmin web, desktop tools, PyCharm DataGrip)
4. ✅ Set breakpoints and inspect variables with debugpy
5. ✅ Test with actual GPIO, audio, and SDR hardware (bare metal advantages)
6. ✅ Let AI agents like ZenCoder see and modify code in real-time
7. ✅ Commit only working, tested code to GitHub
8. ✅ Debug individual systemd services independently

**Key Points**:
- **Code location**: `/opt/eas-station/` on the server (not `/home/pi/eas-station`)
- **Services**: Managed by systemd (not Docker containers)
- **Database**: Local PostgreSQL on server at `localhost:5432`
- **PyCharm/VS Code** → Code runs on server via SSH → Use `POSTGRES_HOST=localhost`
- **Remote database tools** → Connect to server's IP (e.g., `192.168.1.100:5432`)
- **pgAdmin web** → Access at `https://SERVER_IP/pgadmin4`
- **Debug ports**: 5678 (web), 5679 (audio), 5680-5684 (other services)

**Perfect for AI coding agents**:
- ZenCoder can see all code changes immediately
- Full database access for querying and debugging
- Real-time log streaming via journalctl
- Direct debugpy integration for deep inspection
- No container isolation - direct hardware access

**No more broken PRs. No more guess-and-check debugging. No more wasted time.**

---

## Getting Help

- **PyCharm Documentation**: [Remote Debugging with PyCharm](https://www.jetbrains.com/help/pycharm/remote-debugging-with-product.html)
- **VS Code Remote SSH**: [VS Code Remote Development](https://code.visualstudio.com/docs/remote/ssh)
- **debugpy Documentation**: [Python Debugger](https://github.com/microsoft/debugpy)
- **systemd Documentation**: [systemd.io](https://systemd.io/)
- **EAS Station Issues**: [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
- **EAS Station Discussions**: [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)

---

**Last Updated**: 2025-12-10
**Maintained By**: EAS Station Development Team
