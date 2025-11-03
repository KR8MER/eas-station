# Navigation Redesign Plan

## Current Issues

1. **Too Many Dropdowns**: 5 main dropdowns (Monitoring, Operations, Analytics, Settings, User)
2. **Redundancy**: "Active Alerts" and "Alert History" both go to /alerts
3. **Poor Grouping**: Related items scattered across different menus
4. **Export Functions**: Hidden in Analytics dropdown
5. **Debug/Admin**: Mixed with user-facing features

## Proposed New Structure

### Primary Navigation (Always Visible)

```
┌─────────────────────────────────────────────────────────────┐
│ [Logo] EAS Station                    [User] [Theme] [Help] │
├─────────────────────────────────────────────────────────────┤
│ Dashboard | Alerts | Operations | System | Help             │
└─────────────────────────────────────────────────────────────┘
```

### Simplified Menu Structure

#### 1. Dashboard (No Dropdown)
- Direct link to main dashboard
- Shows overview of system status, active alerts, recent activity

#### 2. Alerts (Dropdown)
```
Alerts
├── Active Alerts
├── Alert History
├── Audio Archive
└── Alert Validation (🔒 requires auth)
```

#### 3. Operations (Dropdown)
```
Operations
├── EAS Workflow (🔒 requires auth)
├── LED Control
├── Radio Settings
└── Compliance (🔒 requires auth)
```

#### 4. System (Dropdown)
```
System
├── System Health
├── Statistics
├── Configuration (🔒 requires auth)
├── ─────────────
├── Export Data
│   ├── Export Alerts
│   ├── Export Boundaries
│   └── Export Statistics
└── ─────────────
└── Advanced
    ├── IPAWS Debug
    └── Version Info
```

#### 5. Help (Dropdown)
```
Help
├── Documentation
├── About
└── Support
```

### Utility Navigation (Right Side)

```
[User Menu] [Theme Toggle]
```

**User Menu (when authenticated):**
```
[Username] ▼
├── Profile
├── Settings
└── Logout
```

**User Menu (when not authenticated):**
```
[Login]
```

## Benefits of New Structure

1. **Clearer Organization**: Related items grouped logically
2. **Fewer Clicks**: Most common actions in top-level menu
3. **Better Mobile**: Simpler structure works better on small screens
4. **Progressive Disclosure**: Advanced features hidden in submenus
5. **Consistent Patterns**: Similar items grouped together

## Implementation Plan

### Step 1: Update Navigation HTML
- Simplify dropdown structure
- Remove redundant items
- Group related functions
- Add proper ARIA labels

### Step 2: Update Navigation CSS
- Apply design system colors
- Improve hover/focus states
- Better mobile responsiveness
- Smooth transitions

### Step 3: Add Keyboard Navigation
- Tab through all items
- Arrow keys in dropdowns
- Escape to close
- Enter to activate

### Step 4: Test
- Test all links work
- Test on mobile devices
- Test keyboard navigation
- Test with screen readers

## Mobile Navigation

On mobile (< 768px), navigation collapses to hamburger menu:

```
┌─────────────────────────────┐
│ [☰] EAS Station    [Theme]  │
└─────────────────────────────┘

When expanded:
┌─────────────────────────────┐
│ [×] EAS Station    [Theme]  │
├─────────────────────────────┤
│ Dashboard                   │
│ Alerts              [▼]     │
│ Operations          [▼]     │
│ System              [▼]     │
│ Help                [▼]     │
│ ─────────────────────────   │
│ [User Menu]                 │
└─────────────────────────────┘
```

## Accessibility Features

1. **ARIA Labels**: All interactive elements labeled
2. **Keyboard Navigation**: Full keyboard support
3. **Focus Indicators**: Clear visual focus states
4. **Screen Reader**: Proper semantic HTML
5. **Skip Links**: Skip to main content

## Next Steps

1. Create new navigation component
2. Update base.html
3. Test thoroughly
4. Document for developers