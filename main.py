"""
Auto Curve Shaper - Main Entry Point

Automatic AMD Zen 5 CurveShaper voltage curve optimization tool
Target: Maximum CPU frequency through optimal voltage curve
"""
import sys
import logging
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config import RESULTS_DIR, LOGS_DIR, VERSION
from optimizer import Optimizer
from utils import check_admin_privileges, save_json, logger
from state_manager import OptimizationState


def setup_directories():
    """Create necessary directories"""
    RESULTS_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)


def main():
    """Main entry point"""
    print(f"""
╔════════════════════════════════════════════════════════════════╗
║        Auto Curve Shaper v{VERSION} - AMD Zen 5 Optimizer                 ║
║        Target: Maximum Frequency                               ║
╚════════════════════════════════════════════════════════════════╝
    """)
    
    # Setup
    setup_directories()
    
    # Check admin privileges
    if not check_admin_privileges():
        logger.error("This tool requires Administrator privileges!")
        logger.error("Please run as Administrator.")
        sys.exit(1)
    
    logger.info("Running with Administrator privileges ✓")
    
    # Check for existing state
    existing_state = OptimizationState.load()
    if existing_state:
        print(f"\n🔄 Found existing optimization state:")
        print(f"   Status: {existing_state.status}")
        print(f"   Iteration: {existing_state.iteration}")
        print(f"   Reboots: {existing_state.total_reboots}")
        print(f"   Cells optimized: {len(existing_state.cells_optimized)} / 15")
        print(f"   Best frequency: {existing_state.best_frequency:.0f} MHz")
        
        if existing_state.status == "completed":
            print("\n✅ Optimization already completed!")
            print("\nBest configuration:")
            from config import ROW_NAMES
            for row_idx, row in enumerate(existing_state.best_grid):
                print(f"   {ROW_NAMES[row_idx]:5s}: {' '.join([f'{v:+3d}' for v in row])}")
            
            response = input("\nStart new optimization? (yes/no): ").strip().lower()
            if response != 'yes':
                print("Exiting.")
                sys.exit(0)
            else:
                # Reset state
                existing_state.reset()
                existing_state.save()
                logger.info("State reset for new optimization run")
    
    print("\n⚠️  WARNING:")
    print("   - This tool will reboot your system multiple times (50-100+ reboots)")
    print("   - Each iteration requires a reboot to apply CurveShaper changes")
    print("   - Save all work before continuing")
    print("   - The optimization may take several hours to days")
    print("   - Unstable settings may cause system crashes (WHEA errors)")
    
    response = input("\n❓ Continue with optimization? (yes/no): ").strip().lower()
    if response != 'yes':
        print("Optimization cancelled.")
        sys.exit(0)
    
    # Run optimizer
    try:
        logger.info("Starting optimization...")
        optimizer = Optimizer()
        results = optimizer.run()
        
        # Save results
        results_file = RESULTS_DIR / f"results_{results['timestamp'].replace(':', '-')}.json"
        save_json(results, results_file)
        
        print(f"\n✅ Optimization complete! Results saved to: {results_file}")
        
    except SystemExit as e:
        # Normal exit for reboot
        logger.info(str(e))
        print(f"\n{e}")
        sys.exit(0)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Optimization interrupted by user")
        logger.warning("Interrupted by user")
        sys.exit(1)
    
    except Exception as e:
        logger.error(f"Optimization failed: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
