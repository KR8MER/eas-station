#!/usr/bin/env python3
"""
Cleanup script to remove boundaries with Unknown names
"""
import os
import sys

# Add project directory to Python path
sys.path.insert(0, '/home/pi/noaa_alerts_system')

# Set working directory
os.chdir('/home/pi/noaa_alerts_system')

from app import app, db, Boundary

def cleanup_unknown_boundaries():
    """Remove boundaries with Unknown names"""
    with app.app_context():
        try:
            # Find all boundaries with Unknown names
            unknown_boundaries = Boundary.query.filter_by(name='Unknown').all()
            
            print(f"Found {len(unknown_boundaries)} boundaries with 'Unknown' names")
            
            # Group by type
            by_type = {}
            for boundary in unknown_boundaries:
                if boundary.type not in by_type:
                    by_type[boundary.type] = []
                by_type[boundary.type].append(boundary)
            
            print("\nBreakdown by type:")
            for boundary_type, boundaries in by_type.items():
                print(f"  {boundary_type}: {len(boundaries)}")
            
            # Ask for confirmation
            response = input(f"\nDo you want to delete all {len(unknown_boundaries)} 'Unknown' boundaries? (yes/no): ")
            
            if response.lower() in ['yes', 'y']:
                # Delete them
                for boundary in unknown_boundaries:
                    db.session.delete(boundary)
                
                db.session.commit()
                print(f"✅ Deleted {len(unknown_boundaries)} boundaries with 'Unknown' names")
                
                # Show remaining boundaries
                remaining = Boundary.query.count()
                print(f"📊 {remaining} boundaries remaining in database")
                
            else:
                print("❌ Cleanup cancelled")
                
        except Exception as e:
            db.session.rollback()
            print(f"Error: {e}")

if __name__ == '__main__':
    cleanup_unknown_boundaries()
