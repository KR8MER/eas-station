#!/usr/bin/env python3
"""
Fix admin users that don't have roles assigned.

This script assigns the 'admin' role to any AdminUser that has no role.
Run this after installation if admin users show "No Role" in the UI.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_core.minimal_app import create_minimal_app
from app_core.extensions import db
from app_core.models import AdminUser
from app_core.auth.roles import Role, initialize_default_roles_and_permissions

def fix_admin_roles():
    """Assign admin role to users without roles."""
    app = create_minimal_app()
    
    with app.app_context():
        # First, ensure roles are initialized
        print("Initializing roles and permissions...")
        try:
            initialize_default_roles_and_permissions()
            db.session.commit()
            print("✓ Roles and permissions initialized")
        except Exception as e:
            print(f"⚠ Warning initializing roles (may already exist): {e}")
            db.session.rollback()
        
        # Get the admin role
        admin_role = Role.query.filter_by(name='admin').first()
        if not admin_role:
            print("✗ ERROR: Admin role not found in database!")
            print("  Please check database initialization.")
            return False
        
        print(f"✓ Found admin role (ID: {admin_role.id}) with {len(admin_role.permissions)} permissions")
        
        # Find users without roles
        users_without_roles = AdminUser.query.filter(AdminUser.role_id.is_(None)).all()
        
        if not users_without_roles:
            print("✓ All users already have roles assigned")
            return True
        
        print(f"\nFound {len(users_without_roles)} user(s) without roles:")
        for user in users_without_roles:
            print(f"  - {user.username} (ID: {user.id})")
        
        # Assign admin role to users without roles
        print("\nAssigning admin role...")
        for user in users_without_roles:
            user.role_id = admin_role.id
            db.session.add(user)
            print(f"  ✓ Assigned admin role to {user.username}")
        
        db.session.commit()
        print("\n✓ Successfully fixed all users!")
        
        # Verify
        print("\nVerification:")
        all_users = AdminUser.query.all()
        for user in all_users:
            role_name = user.role.name if user.role else "No Role"
            print(f"  - {user.username}: {role_name}")
        
        return True

if __name__ == '__main__':
    try:
        success = fix_admin_roles()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
