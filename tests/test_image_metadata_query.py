import numpy as np
import pytest


def test_nifti_metadata_is_structured_and_localized(tmp_path, monkeypatch):
    sitk = pytest.importorskip("SimpleITK")
    from agent_runtime.core import ToolResultPipeline
    from tool_factory.doc_reader import DocumentReaderTool

    image = sitk.GetImageFromArray(
        np.arange(24, dtype=np.int16).reshape(2, 3, 4)
    )
    image.SetSpacing((0.7, 0.8, 2.5))
    image.SetOrigin((10.0, 20.0, -30.0))
    image.SetDirection((1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0))
    path = tmp_path / "uploaded_ct.nii.gz"
    sitk.WriteImage(image, str(path))
    monkeypatch.setenv("BRACHYBOT_FILESYSTEM_ROOTS", str(tmp_path))

    result = DocumentReaderTool()._execute(
        file_path=str(path),
        action="metadata",
    )

    assert result.success is True
    assert result.metadata["format"] == "NIfTI"
    assert result.metadata["size_xyz"] == [4, 3, 2]
    assert result.metadata["array_shape_zyx"] == [2, 3, 4]
    assert result.metadata["spacing_mm_xyz"] == pytest.approx([0.7, 0.8, 2.5])
    assert result.metadata["voxel_count"] == 24
    assert result.metadata["value_min"] == 0.0
    assert result.metadata["value_max"] == 23.0

    zh = ToolResultPipeline.format("doc_reader", result, "zh")
    en = ToolResultPipeline.format("doc_reader", result, "en")
    assert "24" in zh and "0.7" in zh
    assert "Current CT Image Technical Metadata" not in zh
    assert "Current CT Image Technical Metadata" in en
    assert "Document metadata extracted" not in en


def test_image_metadata_requests_use_local_policy():
    from agent_runtime.turn_policy import classify_local_turn

    assert classify_local_turn("\u67e5\u770b\u56fe\u50cf\u7684\u8be6\u7ec6\u4fe1\u606f").intent == "image_metadata_query"
    assert classify_local_turn("\u5e2e\u6211\u5206\u6790\u4e00\u4e0b\u6211\u4e0a\u4f20\u7684\u56fe\u50cf").intent == "image_metadata_query"
    assert classify_local_turn("show me the uploaded image metadata").intent == "image_metadata_query"
    assert classify_local_turn("\u8bf7\u5206\u5272\u80f0\u817a CTV").intent == "segmentation"


def test_local_chat_response_reads_the_active_ct_state():
    from agent_runtime.chat_workflows import ChatWorkflowMixin

    class Memory:
        def __init__(self):
            self.values = {
                "ct_path": "/private/workspace/inputs/patient_ct.nii.gz",
                "ct_shape": [2, 3, 4],
                "ct_spacing": [0.7, 0.8, 2.5],
                "ct_origin": [10.0, 20.0, -30.0],
                "ct_direction": [1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0],
                "ct_data": np.arange(24, dtype=np.int16).reshape(2, 3, 4),
                "ct_window_center": 40,
                "ct_window_width": 400,
            }

        def retrieve(self, key):
            return self.values.get(key)

    agent = ChatWorkflowMixin()
    agent.memory = Memory()
    response = agent._build_current_image_metadata_response("zh")

    assert "\u5f53\u524d CT \u56fe\u50cf\u6280\u672f\u4fe1\u606f" in response
    assert "patient_ct.nii.gz" in response
    assert "4 x 3 x 2" in response
    assert "0.7 x 0.8 x 2.5" in response
    assert "/private/workspace" not in response
    assert "\u5143\u6570\u636e\u5df2\u63d0\u53d6" not in response
