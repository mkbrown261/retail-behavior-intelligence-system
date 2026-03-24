import React, { useState } from 'react'
import {
  Terminal, Package, Cpu,
  ChevronDown, ChevronRight,
  CheckCircle2, Circle, Copy, Check,
  AlertTriangle, Info, Zap, Globe, Wifi,
  ArrowRight, BookOpen
} from 'lucide-react'

/* ─────────────────────────────────────────────────────────────────────────────
   Data — all three installation paths defined in one place
───────────────────────────────────────────────────────────────────────────── */

const METHODS = [
  {
    id: 'python',
    icon: Terminal,
    label: 'Python Setup',
    sublabel: 'Manual Install',
    accentColor: '#58a6ff',
    accentBg: 'rgba(88,166,255,0.08)',
    accentBorder: 'rgba(88,166,255,0.35)',
    tag: 'For Developers',
    tagColor: 'badge-low',
    description:
      'Full control over the environment. Best for developers or IT staff who are comfortable running terminal commands.',
    bestFor: ['You have Python installed (or can install it)', 'You want to customize the setup', 'Running on a standard PC or server'],
    estimatedTime: '10–15 min',
    steps: [
      {
        title: 'Install Python 3.10 or later',
        detail: 'RBIS requires Python 3.10+. Check your version first — if it\'s already installed you can skip the download.',
        commands: [
          { label: 'Check your Python version', cmd: 'python3 --version' },
          { label: 'If not installed, download from', cmd: 'https://python.org/downloads', isLink: true },
        ],
        note: 'Windows: make sure you tick "Add Python to PATH" during installation.',
      },
      {
        title: 'Install Git',
        detail: 'Git lets you download the RBIS code and keep it up to date.',
        commands: [
          { label: 'Check if Git is already installed', cmd: 'git --version' },
          { label: 'If not installed, download from', cmd: 'https://git-scm.com', isLink: true },
          { label: 'Linux (Debian/Ubuntu)', cmd: 'sudo apt install git' },
        ],
      },
      {
        title: 'Clone the repository',
        detail: 'This downloads the full RBIS codebase to your computer.',
        commands: [
          { label: 'Clone', cmd: 'git clone https://github.com/mkbrown261/retail-behavior-intelligence-system' },
          { label: 'Enter the project folder', cmd: 'cd retail-behavior-intelligence-system' },
        ],
      },
      {
        title: 'Configure your environment',
        detail: 'Copy the example config file and set your secret key. RBIS will not start without a SECRET_KEY.',
        commands: [
          { label: 'Copy the template', cmd: 'cp backend/.env.example backend/.env' },
          { label: 'Generate a secure secret key', cmd: 'python3 -c "import secrets; print(secrets.token_hex(32))"' },
          { label: 'Open .env and paste the key next to SECRET_KEY=', cmd: 'nano backend/.env', isNote: true },
        ],
        note: 'Never share or commit the .env file. It is already in .gitignore.',
      },
      {
        title: 'Start the system',
        detail: 'This one command installs all dependencies and starts the backend server.',
        commands: [
          { label: 'Mac / Linux', cmd: 'bash run.sh' },
          { label: 'Windows — double-click', cmd: 'run.bat', isNote: true },
        ],
        note: 'The first run takes 2–5 minutes to install packages. Subsequent starts are instant.',
      },
      {
        title: 'Open the dashboard',
        detail: 'Once you see "System ready" in the terminal, open a browser.',
        commands: [
          { label: 'This computer', cmd: 'http://localhost:8000' },
          { label: 'Phone / tablet on same Wi-Fi', cmd: 'http://<your-local-ip>:8000', isNote: true },
        ],
        note: 'Your local IP is printed in the terminal when the server starts.',
        isFinal: true,
      },
    ],
  },
  {
    id: 'docker',
    icon: Package,
    label: 'Docker Setup',
    sublabel: 'Recommended',
    accentColor: '#3fb950',
    accentBg: 'rgba(63,185,80,0.08)',
    accentBorder: 'rgba(63,185,80,0.35)',
    tag: 'Recommended',
    tagColor: 'badge-normal',
    description:
      'The fastest way to run RBIS. Docker packages everything — Python, libraries, dependencies — into one container you just run.',
    bestFor: ['You want to be running in under 5 minutes', 'You don\'t want to manage Python versions', 'Running on a server, VPS, or NAS'],
    estimatedTime: '5 min (after Docker installed)',
    steps: [
      {
        title: 'What is Docker?',
        detail: 'Docker is like a self-contained box that holds the entire application and everything it needs to run. You don\'t have to install Python, libraries, or configure anything — you just start the box.',
        commands: [
          { label: 'Install Docker Desktop (Windows / Mac)', cmd: 'https://docker.com/products/docker-desktop', isLink: true },
          { label: 'Install Docker on Linux (Ubuntu)', cmd: 'sudo apt update && sudo apt install docker.io docker-compose -y' },
          { label: 'Verify Docker is running', cmd: 'docker --version' },
        ],
      },
      {
        title: 'Clone the repository',
        detail: 'Download the RBIS project files.',
        commands: [
          { cmd: 'git clone https://github.com/mkbrown261/retail-behavior-intelligence-system' },
          { cmd: 'cd retail-behavior-intelligence-system' },
        ],
      },
      {
        title: 'Configure your environment',
        detail: 'Docker still needs your secret key to run securely.',
        commands: [
          { label: 'Copy template', cmd: 'cp backend/.env.example backend/.env' },
          { label: 'Generate secret key', cmd: 'python3 -c "import secrets; print(secrets.token_hex(32))"' },
          { label: 'Paste key into backend/.env next to SECRET_KEY=', cmd: 'nano backend/.env', isNote: true },
        ],
        note: 'If you don\'t have Python, Docker can generate it: docker run --rm python:3.11 python3 -c "import secrets; print(secrets.token_hex(32))"',
      },
      {
        title: 'Start RBIS with Docker Compose',
        detail: 'One command builds and starts everything. The -d flag runs it in the background.',
        commands: [
          { label: 'Build and start (background)', cmd: 'docker-compose up -d' },
          { label: 'First run (watch progress)', cmd: 'docker-compose up' },
          { label: 'Check it is running', cmd: 'docker-compose ps' },
        ],
        note: 'First run downloads the base image and installs packages — about 3–5 minutes. Every run after that is instant.',
      },
      {
        title: 'Open the dashboard',
        detail: 'Once the container is running, the dashboard is live.',
        commands: [
          { label: 'Local browser', cmd: 'http://localhost:8000' },
          { label: 'Phone on same Wi-Fi', cmd: 'http://<your-local-ip>:8000', isNote: true },
        ],
        isFinal: true,
      },
      {
        title: 'Docker management commands',
        detail: 'Useful day-to-day Docker commands.',
        commands: [
          { label: 'Stop RBIS', cmd: 'docker-compose down' },
          { label: 'Restart RBIS', cmd: 'docker-compose restart' },
          { label: 'View live logs', cmd: 'docker-compose logs -f' },
          { label: 'Update to latest code', cmd: 'git pull && docker-compose up -d --build' },
        ],
      },
    ],
  },
  {
    id: 'pi',
    icon: Cpu,
    label: 'Raspberry Pi',
    sublabel: 'Edge Deployment',
    accentColor: '#bc8cff',
    accentBg: 'rgba(188,140,255,0.08)',
    accentBorder: 'rgba(188,140,255,0.35)',
    tag: 'Edge Device',
    tagColor: 'badge-medium',
    description:
      'Deploy RBIS directly onto a Raspberry Pi that you install on-site. The Pi handles all camera processing locally — no internet required after setup.',
    bestFor: ['Installing at a customer\'s store', 'No PC available on-site', 'Permanent always-on deployment'],
    estimatedTime: '15–20 min (one time)',
    steps: [
      {
        title: 'What you need',
        detail: 'Gather your hardware before starting.',
        isList: true,
        listItems: [
          'Raspberry Pi 4 (2 GB RAM minimum, 4 GB recommended) or Raspberry Pi 5',
          'MicroSD card — 32 GB or larger (Class 10 / A2 speed rating)',
          'Raspberry Pi OS installed (Bullseye or Bookworm, 64-bit recommended)',
          'Internet connection during setup (Wi-Fi or ethernet)',
          'Power supply (official Pi power adapter recommended)',
        ],
        commands: [
          { label: 'Flash the OS using Raspberry Pi Imager', cmd: 'https://raspberrypi.com/software', isLink: true },
        ],
        note: 'When flashing with Pi Imager, click the gear icon to pre-configure Wi-Fi, hostname, and SSH — this saves time.',
      },
      {
        title: 'Get the Pi connected',
        detail: 'Either connect a keyboard + monitor directly, or SSH in from your laptop.',
        commands: [
          { label: 'Find Pi\'s IP address (from your router or the Pi screen)', cmd: 'hostname -I' },
          { label: 'SSH from your laptop (replace the IP)', cmd: 'ssh pi@192.168.1.xxx' },
        ],
        note: 'Default credentials are usually username: pi, password: raspberry — change these after first login.',
      },
      {
        title: 'Clone the repository',
        detail: 'Download RBIS onto the Pi.',
        commands: [
          { cmd: 'git clone https://github.com/mkbrown261/retail-behavior-intelligence-system' },
          { cmd: 'cd retail-behavior-intelligence-system' },
        ],
      },
      {
        title: 'Run the Pi setup script',
        detail: 'This one script does everything: installs system packages, sets up Python, configures your .env, and registers RBIS as a service that starts automatically on every boot.',
        commands: [
          { label: 'Run the setup script', cmd: 'bash setup-pi.sh' },
        ],
        note: 'Takes 5–10 minutes. The Pi will set its hostname to "rbis" so you can reach it at http://rbis.local:8000 from any device on the same network.',
      },
      {
        title: 'Verify it is running',
        detail: 'After setup completes, check the service status.',
        commands: [
          { label: 'Check service status', cmd: 'sudo systemctl status rbis' },
          { label: 'Watch live logs', cmd: 'sudo journalctl -u rbis -f' },
          { label: 'Test the health endpoint', cmd: 'curl http://localhost:8000/api/health' },
        ],
      },
      {
        title: 'Access the dashboard',
        detail: 'Open a browser on any device connected to the same Wi-Fi.',
        commands: [
          { label: 'Using the Pi hostname (easiest)', cmd: 'http://rbis.local:8000' },
          { label: 'Using the Pi\'s IP address', cmd: 'http://192.168.1.xxx:8000', isNote: true },
        ],
        isFinal: true,
        note: 'The Pi auto-starts RBIS on every boot. No screen, keyboard, or login needed — just power and network.',
      },
      {
        title: 'Day-to-day Pi management',
        detail: 'Commands for managing RBIS on the Pi after installation.',
        commands: [
          { label: 'Start', cmd: 'sudo systemctl start rbis' },
          { label: 'Stop', cmd: 'sudo systemctl stop rbis' },
          { label: 'Restart', cmd: 'sudo systemctl restart rbis' },
          { label: 'Update to latest code', cmd: 'cd ~/retail-behavior-intelligence-system && git pull && sudo systemctl restart rbis' },
        ],
      },
    ],
  },
]

/* ─────────────────────────────────────────────────────────────────────────────
   Small helper: copy-to-clipboard code block
───────────────────────────────────────────────────────────────────────────── */
function CodeBlock({ cmd, isLink, isNote }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(cmd).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    })
  }

  if (isLink) {
    return (
      <a
        href={cmd}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          color: 'var(--accent-blue)',
          textDecoration: 'none',
          fontSize: 13,
          fontFamily: 'inherit',
          background: 'rgba(88,166,255,0.08)',
          border: '1px solid rgba(88,166,255,0.25)',
          borderRadius: 6,
          padding: '5px 12px',
        }}
      >
        <Globe size={12} />
        {cmd}
      </a>
    )
  }

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      background: isNote ? 'transparent' : 'var(--rbis-900)',
      border: isNote ? 'none' : '1px solid var(--rbis-600)',
      borderRadius: 6,
      padding: isNote ? '2px 0' : '7px 12px',
      fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
      fontSize: 13,
      color: isNote ? 'var(--rbis-400)' : 'var(--rbis-100)',
    }}>
      {isNote && <Info size={12} style={{ color: 'var(--rbis-500)', flexShrink: 0 }} />}
      <span style={{ flex: 1, wordBreak: 'break-all' }}>{cmd}</span>
      {!isNote && (
        <button
          onClick={handleCopy}
          title="Copy"
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: copied ? 'var(--accent-green)' : 'var(--rbis-500)',
            padding: '2px 4px',
            borderRadius: 4,
            display: 'flex',
            alignItems: 'center',
            flexShrink: 0,
            transition: 'color 0.15s',
          }}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </button>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
   One step inside the expanded method panel
───────────────────────────────────────────────────────────────────────────── */
function Step({ step, index, accentColor, totalSteps }) {
  const isLast = index === totalSteps - 1

  return (
    <div style={{ display: 'flex', gap: 16, position: 'relative' }}>
      {/* Vertical connector line */}
      {!isLast && (
        <div style={{
          position: 'absolute',
          left: 17,
          top: 36,
          bottom: -16,
          width: 1,
          background: 'var(--rbis-700)',
        }} />
      )}

      {/* Step number bubble */}
      <div style={{
        width: 34,
        height: 34,
        borderRadius: '50%',
        background: step.isFinal
          ? `rgba(63,185,80,0.15)`
          : `rgba(88,166,255,0.1)`,
        border: `1px solid ${step.isFinal ? 'rgba(63,185,80,0.4)' : 'rgba(88,166,255,0.3)'}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        marginTop: 2,
      }}>
        {step.isFinal
          ? <CheckCircle2 size={16} style={{ color: 'var(--accent-green)' }} />
          : <span style={{ fontSize: 12, fontWeight: 700, color: accentColor }}>{index + 1}</span>
        }
      </div>

      {/* Step content */}
      <div style={{ flex: 1, paddingBottom: 28 }}>
        <div style={{
          fontSize: 14,
          fontWeight: 700,
          color: 'var(--rbis-100)',
          marginBottom: 6,
          letterSpacing: '0.01em',
        }}>
          {step.title}
        </div>

        <div style={{
          fontSize: 13,
          color: 'var(--rbis-400)',
          marginBottom: step.commands || step.isList ? 12 : 0,
          lineHeight: 1.6,
        }}>
          {step.detail}
        </div>

        {/* Bullet list (What you need) */}
        {step.isList && step.listItems && (
          <ul style={{ margin: '0 0 12px 0', padding: 0, listStyle: 'none' }}>
            {step.listItems.map((item, i) => (
              <li key={i} style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 8,
                fontSize: 13,
                color: 'var(--rbis-300)',
                padding: '3px 0',
              }}>
                <div style={{
                  width: 5,
                  height: 5,
                  borderRadius: '50%',
                  background: accentColor,
                  marginTop: 6,
                  flexShrink: 0,
                  opacity: 0.7,
                }} />
                {item}
              </li>
            ))}
          </ul>
        )}

        {/* Command blocks */}
        {step.commands && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {step.commands.map((c, i) => (
              <div key={i}>
                {c.label && (
                  <div style={{
                    fontSize: 11,
                    color: 'var(--rbis-500)',
                    marginBottom: 3,
                    textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                  }}>
                    {c.label}
                  </div>
                )}
                <CodeBlock cmd={c.cmd} isLink={c.isLink} isNote={c.isNote} />
              </div>
            ))}
          </div>
        )}

        {/* Callout note */}
        {step.note && (
          <div style={{
            marginTop: 10,
            display: 'flex',
            alignItems: 'flex-start',
            gap: 7,
            background: 'rgba(210,153,34,0.07)',
            border: '1px solid rgba(210,153,34,0.25)',
            borderRadius: 6,
            padding: '8px 12px',
            fontSize: 12,
            color: 'var(--accent-yellow)',
            lineHeight: 1.5,
          }}>
            <AlertTriangle size={12} style={{ marginTop: 2, flexShrink: 0 }} />
            <span>{step.note}</span>
          </div>
        )}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
   Expanded panel — full instructions for one method
───────────────────────────────────────────────────────────────────────────── */
function MethodPanel({ method }) {
  return (
    <div style={{
      marginTop: 12,
      background: 'var(--rbis-900)',
      border: `1px solid ${method.accentBorder}`,
      borderRadius: 10,
      overflow: 'hidden',
    }}>
      {/* Panel header strip */}
      <div style={{
        background: method.accentBg,
        borderBottom: `1px solid ${method.accentBorder}`,
        padding: '14px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
      }}>
        <method.icon size={16} style={{ color: method.accentColor }} />
        <span style={{ fontSize: 14, fontWeight: 700, color: method.accentColor }}>
          {method.label} — Step by Step
        </span>
        <span style={{
          marginLeft: 'auto',
          fontSize: 11,
          color: 'var(--rbis-500)',
          display: 'flex',
          alignItems: 'center',
          gap: 4,
        }}>
          <Zap size={10} />
          ~{method.estimatedTime}
        </span>
      </div>

      {/* Steps */}
      <div style={{ padding: '24px 24px 8px' }}>
        {method.steps.map((step, i) => (
          <Step
            key={i}
            step={step}
            index={i}
            accentColor={method.accentColor}
            totalSteps={method.steps.length}
          />
        ))}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
   Selector card — top-level clickable method card
───────────────────────────────────────────────────────────────────────────── */
function MethodCard({ method, isOpen, onToggle }) {
  const Icon = method.icon

  return (
    <div>
      {/* Clickable card header */}
      <button
        onClick={onToggle}
        style={{
          width: '100%',
          textAlign: 'left',
          background: isOpen ? method.accentBg : 'var(--rbis-800)',
          border: `1px solid ${isOpen ? method.accentBorder : 'var(--rbis-600)'}`,
          borderRadius: isOpen ? '10px 10px 0 0' : 10,
          padding: '20px 22px',
          cursor: 'pointer',
          transition: 'all 0.2s',
          display: 'flex',
          alignItems: 'flex-start',
          gap: 16,
        }}
      >
        {/* Icon bubble */}
        <div style={{
          width: 46,
          height: 46,
          borderRadius: 10,
          background: isOpen ? `rgba(255,255,255,0.06)` : 'var(--rbis-700)',
          border: `1px solid ${isOpen ? method.accentBorder : 'var(--rbis-600)'}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          transition: 'all 0.2s',
        }}>
          <Icon size={20} style={{ color: isOpen ? method.accentColor : 'var(--rbis-400)' }} />
        </div>

        {/* Text */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
            <span style={{
              fontSize: 16,
              fontWeight: 700,
              color: isOpen ? method.accentColor : 'var(--rbis-100)',
              transition: 'color 0.2s',
            }}>
              {method.label}
            </span>
            <span style={{
              fontSize: 11,
              color: 'var(--rbis-500)',
              background: 'var(--rbis-700)',
              padding: '1px 7px',
              borderRadius: 4,
            }}>
              {method.sublabel}
            </span>
            <span className={method.tagColor} style={{ fontSize: 10 }}>
              {method.tag}
            </span>
          </div>

          <p style={{
            margin: 0,
            fontSize: 13,
            color: 'var(--rbis-400)',
            lineHeight: 1.55,
            maxWidth: 560,
          }}>
            {method.description}
          </p>

          {/* "Best for" chips */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
            {method.bestFor.map((item, i) => (
              <span key={i} style={{
                fontSize: 11,
                color: 'var(--rbis-400)',
                background: 'var(--rbis-700)',
                border: '1px solid var(--rbis-600)',
                borderRadius: 4,
                padding: '2px 8px',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}>
                <Circle size={4} style={{ color: method.accentColor, fill: method.accentColor }} />
                {item}
              </span>
            ))}
          </div>
        </div>

        {/* Expand chevron */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          flexShrink: 0,
          color: isOpen ? method.accentColor : 'var(--rbis-500)',
          fontSize: 12,
          transition: 'color 0.2s',
        }}>
          <span style={{ display: 'none' }}>{isOpen ? 'Collapse' : 'View steps'}</span>
          {isOpen
            ? <ChevronDown size={18} />
            : <ChevronRight size={18} />
          }
        </div>
      </button>

      {/* Expanded panel — borderless merge with card */}
      {isOpen && (
        <div style={{
          border: `1px solid ${method.accentBorder}`,
          borderTop: 'none',
          borderRadius: '0 0 10px 10px',
          background: 'var(--rbis-900)',
          padding: '24px',
        }}>
          {method.steps.map((step, i) => (
            <Step
              key={i}
              step={step}
              index={i}
              accentColor={method.accentColor}
              totalSteps={method.steps.length}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
   Comparison table (quick reference)
───────────────────────────────────────────────────────────────────────────── */
function ComparisonTable() {
  const rows = [
    { label: 'Setup time',         python: '10–15 min',   docker: '5 min',        pi: '15–20 min' },
    { label: 'Technical skill',    python: 'Intermediate', docker: 'Beginner',    pi: 'Beginner' },
    { label: 'Survives reboot',    python: 'Manual',      docker: 'With compose', pi: 'Auto (systemd)' },
    { label: 'Internet required',  python: 'Setup only',  docker: 'Setup only',   pi: 'Setup only' },
    { label: 'Best hardware',      python: 'PC / Server', docker: 'PC / Server',  pi: 'Raspberry Pi 4/5' },
    { label: 'Add cameras via',    python: 'Dashboard',   docker: 'Dashboard',    pi: 'Dashboard' },
  ]
  const cols = [
    { key: 'python', label: 'Python', color: '#58a6ff' },
    { key: 'docker', label: 'Docker', color: '#3fb950' },
    { key: 'pi',     label: 'Pi',     color: '#bc8cff' },
  ]

  return (
    <div style={{
      background: 'var(--rbis-800)',
      border: '1px solid var(--rbis-600)',
      borderRadius: 10,
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: '180px repeat(3, 1fr)',
        borderBottom: '1px solid var(--rbis-600)',
      }}>
        <div style={{ padding: '10px 16px', fontSize: 11, color: 'var(--rbis-500)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Feature
        </div>
        {cols.map(col => (
          <div key={col.key} style={{
            padding: '10px 16px',
            fontSize: 12,
            fontWeight: 700,
            color: col.color,
            borderLeft: '1px solid var(--rbis-700)',
            textAlign: 'center',
          }}>
            {col.label}
          </div>
        ))}
      </div>
      {rows.map((row, i) => (
        <div key={i} style={{
          display: 'grid',
          gridTemplateColumns: '180px repeat(3, 1fr)',
          borderBottom: i < rows.length - 1 ? '1px solid var(--rbis-700)' : 'none',
          background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
        }}>
          <div style={{
            padding: '10px 16px',
            fontSize: 12,
            color: 'var(--rbis-400)',
          }}>
            {row.label}
          </div>
          {cols.map(col => (
            <div key={col.key} style={{
              padding: '10px 16px',
              fontSize: 12,
              color: 'var(--rbis-200)',
              borderLeft: '1px solid var(--rbis-700)',
              textAlign: 'center',
            }}>
              {row[col.key]}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
   Main page
───────────────────────────────────────────────────────────────────────────── */
export default function SetupGuidePage() {
  const [openMethod, setOpenMethod] = useState(null)

  const toggle = (id) => setOpenMethod(prev => prev === id ? null : id)

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '24px 0 48px' }}>

      {/* ── Page header ───────────────────────────────────────────────────── */}
      <div style={{ marginBottom: 32 }}>
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 7,
          background: 'rgba(88,166,255,0.08)',
          border: '1px solid rgba(88,166,255,0.25)',
          borderRadius: 6,
          padding: '4px 12px',
          fontSize: 11,
          color: 'var(--accent-blue)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          marginBottom: 16,
        }}>
          <BookOpen size={11} />
          Setup Guide
        </div>

        <h1 style={{
          margin: '0 0 10px',
          fontSize: 26,
          fontWeight: 800,
          color: 'var(--rbis-white)',
          letterSpacing: '-0.02em',
          lineHeight: 1.2,
        }}>
          Choose Your Setup Method
        </h1>

        <p style={{
          margin: 0,
          fontSize: 14,
          color: 'var(--rbis-400)',
          lineHeight: 1.65,
          maxWidth: 560,
        }}>
          RBIS can be deployed in multiple ways depending on your environment.
          Select the option that best fits your situation — each path is fully
          self-contained with step-by-step instructions.
        </p>
      </div>

      {/* ── Quick tip banner ──────────────────────────────────────────────── */}
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        background: 'rgba(63,185,80,0.07)',
        border: '1px solid rgba(63,185,80,0.25)',
        borderRadius: 8,
        padding: '12px 16px',
        marginBottom: 24,
        fontSize: 13,
        color: 'var(--rbis-300)',
      }}>
        <Zap size={14} style={{ color: 'var(--accent-green)', marginTop: 1, flexShrink: 0 }} />
        <div>
          <strong style={{ color: 'var(--accent-green)' }}>Not sure which to pick?</strong>
          {' '}Use <strong>Docker</strong> if you just want to get running fast on a PC or Mac.
          Use <strong>Raspberry Pi</strong> if you are installing at a customer site.
          Use <strong>Python</strong> if you want full manual control.
        </div>
      </div>

      {/* ── Method cards ──────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {METHODS.map(method => (
          <MethodCard
            key={method.id}
            method={method}
            isOpen={openMethod === method.id}
            onToggle={() => toggle(method.id)}
          />
        ))}
      </div>

      {/* ── After setup: what's next ──────────────────────────────────────── */}
      <div style={{
        marginTop: 36,
        background: 'var(--rbis-800)',
        border: '1px solid var(--rbis-600)',
        borderRadius: 10,
        padding: '20px 22px',
      }}>
        <div style={{
          fontSize: 13,
          fontWeight: 700,
          color: 'var(--rbis-100)',
          marginBottom: 14,
          display: 'flex',
          alignItems: 'center',
          gap: 7,
        }}>
          <ArrowRight size={14} style={{ color: 'var(--accent-blue)' }} />
          After Setup — Next Steps
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 10,
        }}>
          {[
            {
              icon: Wifi,
              title: 'Add Your First Camera',
              desc: 'Open the dashboard → Cameras → + Add Camera. Supports RTSP, USB, HTTP and ONVIF.',
              color: '#58a6ff',
            },
            {
              icon: Globe,
              title: 'Access from Phone',
              desc: 'Open http://<your-ip>:8000 on any device connected to the same Wi-Fi network.',
              color: '#3fb950',
            },
            {
              icon: CheckCircle2,
              title: 'Confirm System is Running',
              desc: 'The Live Dashboard shows active persons and camera feeds in real time once cameras are connected.',
              color: '#bc8cff',
            },
          ].map((item, i) => (
            <div key={i} style={{
              background: 'var(--rbis-900)',
              border: '1px solid var(--rbis-700)',
              borderRadius: 8,
              padding: '14px 16px',
            }}>
              <item.icon size={16} style={{ color: item.color, marginBottom: 8 }} />
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--rbis-100)', marginBottom: 5 }}>
                {item.title}
              </div>
              <div style={{ fontSize: 12, color: 'var(--rbis-400)', lineHeight: 1.55 }}>
                {item.desc}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Comparison table ──────────────────────────────────────────────── */}
      <div style={{ marginTop: 36 }}>
        <div style={{
          fontSize: 13,
          fontWeight: 700,
          color: 'var(--rbis-100)',
          marginBottom: 14,
          display: 'flex',
          alignItems: 'center',
          gap: 7,
        }}>
          <Info size={14} style={{ color: 'var(--rbis-500)' }} />
          Quick Comparison
        </div>
        <ComparisonTable />
      </div>

    </div>
  )
}
