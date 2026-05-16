"""
AI-BrachyAgent Web API Server
=============================
REST API server with WebSocket support for real-time updates.
Run: python web/server.py
"""

import os
import sys
import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any, Optional

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(WEB_DIR, "app")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app(config: Optional[Dict] = None):
    """Create and configure the Flask application."""
    try:
        from flask import Flask, request, jsonify, send_from_directory
        from flask_cors import CORS
        HAS_FLASK = True
    except ImportError:
        HAS_FLASK = False
        logger.warning("Flask not installed. API endpoints will not be available.")
        return None

    app = Flask(__name__, static_folder=APP_DIR, static_url_path="")
    CORS(app)

    if config is None:
        config = {}

    agent = None
    websocket_clients = []

    def get_agent():
        nonlocal agent
        if agent is None:
            try:
                from AgenticSys import BrachyAgent
                agent = BrachyAgent(
                    session_id=config.get("session_id", "web"),
                    config=config.get("agent_config", {})
                )
                logger.info("BrachyAgent initialized for web server")
            except Exception as e:
                logger.error(f"Failed to initialize BrachyAgent: {e}")
                return None
        return agent

    @app.route("/")
    def index():
        return send_from_directory(APP_DIR, "index.html")

    @app.route("/api/status", methods=["GET"])
    def api_status():
        """Get system status."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        status = agent.get_status()
        status["brain_available"] = agent.brain_available
        return jsonify(status)

    @app.route("/api/plan/preoperative", methods=["POST"])
    def api_preoperative_plan():
        """Run pre-operative planning."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_path = data.get("ct_path")
        ctv_path = data.get("ctv_path")
        oar_path = data.get("oar_path")
        mode = data.get("mode", "rule_based")
        output_dir = data.get("output_dir", "./output")

        if not ct_path:
            return jsonify({"error": "ct_path is required"}), 400

        try:
            result = agent.run_preoperative_plan(
                ct_path=ct_path,
                ctv_path=ctv_path,
                oar_path=oar_path,
                mode=mode,
                output_dir=output_dir,
            )
            return jsonify(result)
        except Exception as e:
            logger.error(f"Preoperative planning failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/plan/intraoperative", methods=["POST"])
    def api_intraoperative_plan():
        """Run intra-operative replanning."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_path = data.get("ct_path")
        original_plan = data.get("original_plan")
        threshold = data.get("deviation_threshold_mm", data.get("threshold", 2.0))
        output_dir = data.get("output_dir", "./output")

        if not ct_path:
            return jsonify({"error": "ct_path is required"}), 400

        try:
            result = agent.run_intraoperative_replan(
                intra_op_ct_path=ct_path,
                original_plan=original_plan,
                deviation_threshold_mm=threshold,
                output_dir=output_dir,
            )
            return jsonify(result)
        except Exception as e:
            logger.error(f"Intraoperative replanning failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        """Natural language chat interface with execution trace."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        message = data.get("message", "")

        if not message:
            return jsonify({"error": "message is required"}), 400

        try:
            result = agent.chat_with_trace(message)
            return jsonify({
                "response": result["response"],
                "steps": result["steps"],
                "session_id": agent.memory.session_id,
                "brain_available": agent.brain_available,
            })
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/export/dicom", methods=["POST"])
    def api_export_dicom():
        """Export plan to DICOM RT format."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        output_dir = data.get("output_dir", "./dicom_export")

        try:
            ct_image = agent.memory.retrieve("ct_image")
            if ct_image is None:
                return jsonify({"error": "No CT image in memory. Run planning first."}), 400

            seed_positions = agent.memory.retrieve("seed_positions")
            dose_distribution = agent.memory.retrieve("dose_distribution")
            ctv_array = agent.memory.retrieve("ctv_array")
            oar_array = agent.memory.retrieve("oar_array")

            structures = {}
            if ctv_array is not None:
                structures["CTV"] = ctv_array
            if oar_array is not None:
                structures["OAR"] = oar_array

            from tool_factory.output.dicom_rt_exporter import DicomRTExporterTool
            exporter = DicomRTExporterTool()

            result = exporter._execute(
                ct_image=ct_image,
                structures=structures,
                dose_array=dose_distribution,
                seeds=seed_positions or [],
                output_dir=output_dir,
            )

            if result.success:
                return jsonify({
                    "success": True,
                    "files": result.data,
                    "message": result.message,
                })
            else:
                return jsonify({"error": result.error}), 500

        except Exception as e:
            logger.error(f"DICOM export failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/export/report", methods=["POST"])
    def api_export_report():
        """Generate planning report."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        output_path = data.get("output_path", "./report.json")
        output_format = data.get("format", "json")

        try:
            metrics = agent.memory.retrieve("metrics", {})
            plan_score = metrics.get("plan_score", 0)
            total_seeds = metrics.get("total_seeds", 0)
            total_trajectories = metrics.get("num_trajectories", 0)

            from tool_factory.output.report_generator import ReportGeneratorTool
            generator = ReportGeneratorTool()

            result = generator._execute(
                patient_id=agent.memory.patient_data.get("id", "UNKNOWN"),
                plan_name="BrachyPlan",
                output_path=output_path,
                output_format=output_format,
                ctv_metrics={"voxels": int(metrics.get("ctv_voxel_count", 0))},
                dose_metrics=metrics,
                plan_score=plan_score,
                total_seeds=total_seeds,
                total_trajectories=total_trajectories,
            )

            if result.success:
                return jsonify({
                    "success": True,
                    "path": result.data,
                    "message": result.message,
                })
            else:
                return jsonify({"error": result.error}), 500

        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/reset", methods=["POST"])
    def api_reset():
        """Reset agent state."""
        nonlocal agent
        agent = None
        return jsonify({"success": True, "message": "Agent reset"})

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error"}), 500

    return app


def run_server(port: int = 8080, host: str = "0.0.0.0", config: Optional[Dict] = None):
    """Run the web server."""
    app = create_app(config)

    if app is None:
        logger.error("Cannot start server - Flask not available")
        logger.info("Install Flask: pip install flask flask-cors")
        return

    print(f"\n{'=' * 50}")
    print(f"  AI-BrachyAgent Web Server")
    print(f"  API: http://localhost:{port}/api/*")
    print(f"  Docs: http://localhost:{port}/api/status")
    print(f"  Press Ctrl+C to stop")
    print(f"{'=' * 50}\n")

    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\nServer stopped.")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AI-BrachyAgent Web Server")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--session", default="web", help="Session ID")
    args = parser.parse_args()

    config = {
        "session_id": args.session,
        "agent_config": {},
    }

    run_server(port=args.port, host=args.host, config=config)


if __name__ == "__main__":
    main()