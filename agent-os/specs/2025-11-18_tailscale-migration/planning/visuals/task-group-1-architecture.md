# Task Group 1: Architecture Diagram

## Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Task Group 1: Account Setup                  │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────┐
│   Tailscale Admin    │
│      Console         │
│                      │
│  - Organization      │
│  - Auth Keys         │
│  - ACL Policy        │
└──────────┬───────────┘
           │
           │ 1. User accesses console
           │ 2. Generates auth key
           │ 3. Applies ACL policy
           │
           ▼
┌──────────────────────┐
│    User Actions      │
│                      │
│  - Document org      │
│  - Copy auth key     │
│  - Apply ACL         │
└──────────┬───────────┘
           │
           │ 3. Store auth key
           │
           ▼
┌──────────────────────────────────────────────┐
│            Vault Storage                     │
│                                              │
│  Location: https://192.168.10.101:8200      │
│  Path: secret/tailscale/auth-keys           │
│  Policy: tailscale-k8s                      │
│                                              │
│  ┌────────────────────────────────┐         │
│  │  Auth Key (encrypted at rest)  │         │
│  │  - auth_key: tskey-auth-...    │         │
│  │  - created_by: username        │         │
│  │  - created_at: timestamp       │         │
│  └────────────────────────────────┘         │
└──────────────────────────────────────────────┘
           │
           │ 4. Future: K8s operator reads
           │
           ▼
┌──────────────────────────────────────────────┐
│     Tailscale Kubernetes Operator            │
│          (Task Group 2)                      │
│                                              │
│  - Reads auth key from Vault                │
│  - Authenticates nodes to tailnet           │
│  - Manages device lifecycle                 │
└──────────────────────────────────────────────┘
```

## Data Flow

### Step 1: Organization Setup
```
User → Tailscale Console → Document Details
                         ↓
              organization-info.txt
```

### Step 2: Auth Key Generation
```
User → Tailscale Console → Generate Auth Key
                         ↓
                Settings:
                - Reusable: Yes
                - Tags: kubernetes, homelab
                - Expiration: 365 days
                         ↓
                Copy auth key to clipboard
```

### Step 3: Vault Storage
```
User → store-auth-key.sh → Vault API
                         ↓
              Vault Secret Created
              secret/tailscale/auth-keys
                         ↓
              Vault Policy Created
              tailscale-k8s
```

### Step 4: ACL Application
```
User → Copy acl-policy-permissive.json
     ↓
Tailscale Console ACL Editor
     ↓
Save & Apply
     ↓
ACL Active in Tailnet
```

## Security Architecture

```
┌────────────────────────────────────────────────────────┐
│                   Security Layers                      │
└────────────────────────────────────────────────────────┘

Layer 1: Vault Encryption
┌─────────────────────────────────────────┐
│  Auth key encrypted at rest in Vault   │
│  - Raft storage backend                │
│  - TLS in transit                      │
│  - Token-based authentication          │
└─────────────────────────────────────────┘

Layer 2: Access Control
┌─────────────────────────────────────────┐
│  Vault Policy: tailscale-k8s           │
│  - Read-only access                    │
│  - Limited to auth key path            │
│  - Kubernetes ServiceAccount auth      │
└─────────────────────────────────────────┘

Layer 3: Git Exclusion
┌─────────────────────────────────────────┐
│  .gitignore prevents commits           │
│  - Auth keys                           │
│  - Vault tokens                        │
│  - organization-info.txt               │
└─────────────────────────────────────────┘

Layer 4: Tailscale ACL
┌─────────────────────────────────────────┐
│  ACL Policy controls network access    │
│  - Tag-based device identification     │
│  - User group definitions              │
│  - Service access rules                │
└─────────────────────────────────────────┘
```

## File Structure

```
homelab/
├── tailscale/                          # Main configuration
│   ├── README.md                       # Comprehensive docs
│   ├── QUICKSTART.md                   # Quick reference
│   ├── .gitignore                      # Exclude sensitive files
│   ├── acl-policy-permissive.json     # ACL policy (safe to commit)
│   ├── organization-info-template.txt  # Template
│   ├── organization-info.txt           # Actual info (gitignored)
│   └── scripts/
│       └── store-auth-key.sh          # Vault storage script
│
└── agent-os/specs/2025-11-18_tailscale-migration/
    ├── spec.md                         # Project specification
    ├── tasks.md                        # Task tracking
    ├── planning/
    │   ├── requirements.md             # Detailed requirements
    │   └── visuals/
    │       └── task-group-1-architecture.md  # This file
    └── implementation/
        ├── README.md                   # Implementation overview
        ├── task-group-1-instructions.md  # User instructions
        └── task-group-1-summary.md     # Implementation summary
```

## Integration Points

### With Existing Infrastructure

```
┌──────────────────────────────────────────────────────────┐
│               Existing Infrastructure                    │
└──────────────────────────────────────────────────────────┘

Vault (192.168.10.101:8200)
├── Version: 1.18.3
├── Status: Initialized, unsealed
├── Backend: Raft
└── Namespace: vault
     │
     └── New Path: secret/tailscale/auth-keys
         └── New Policy: tailscale-k8s

Kubernetes Cluster
├── Nodes: km01, km02, km03
├── Namespace: tailscale (to be created in Task Group 2)
└── Future: Tailscale operator deployment
```

### With Future Components

```
Task Group 1 (Current)
    ↓
    Provides: Auth keys in Vault
    Provides: ACL policy in Tailscale
    ↓
Task Group 2 (Next)
    ↓
    Uses: Auth keys from Vault
    Creates: Tailscale operator in K8s
    Creates: Tailnet nodes (km01, km02, km03)
    ↓
Task Group 3
    ↓
    Configures: MagicDNS
    Uses: Tailnet nodes from Task Group 2
    ↓
[Additional task groups...]
```

## Success Criteria Visualization

```
Task Group 1 Complete When:

[✓] Organization documented
     └── organization-info.txt created

[✓] Auth key generated
     └── Settings: reusable, tags, 365 days

[✓] Auth key in Vault
     └── Path: secret/tailscale/auth-keys
     └── Policy: tailscale-k8s created

[✓] ACL policy applied
     └── Tailscale console shows active policy
     └── Tags defined: kubernetes, homelab

[✓] Files committed to git
     └── Configuration files
     └── Documentation
     └── Scripts
     └── (Excluding sensitive data)

Ready for Task Group 2 ──→ Operator Deployment
```

## User Interaction Points

```
Automated Steps:
├── Script: store-auth-key.sh
├── File creation: All docs and configs
└── Git operations: (user performs)

Manual Steps (Required):
├── 1. Access Tailscale admin console
├── 2. Document organization details
├── 3. Generate auth key with correct settings
├── 4. Copy auth key to clipboard
├── 5. Run store-auth-key.sh script
├── 6. Paste auth key when prompted
├── 7. Copy ACL policy content
├── 8. Paste into Tailscale ACL editor
└── 9. Save ACL policy

Cannot Be Automated:
├── Tailscale admin console login (MFA, auth)
├── Auth key generation (requires UI interaction)
├── ACL policy application (requires UI interaction)
└── Organization verification (requires human judgment)
```

## Timeline

```
Task Group 0: Monitoring (COMPLETE)
     ↓
Task Group 1: Account Setup (CURRENT)
     │
     ├── Implementation: 2 hours
     │   └── Created all files, scripts, docs
     │
     └── User Execution: 15-30 minutes
         ├── Access console: 2 min
         ├── Document org: 3 min
         ├── Generate auth key: 5 min
         ├── Store in Vault: 3 min
         └── Apply ACL: 5 min
     ↓
Task Group 2: Operator Deployment (NEXT)
```

## Notes

- This is a foundational task group
- All subsequent task groups depend on this setup
- Manual steps cannot be avoided due to Tailscale console requirements
- Security is prioritized with Vault storage and git exclusions
- Documentation is comprehensive to support user execution
