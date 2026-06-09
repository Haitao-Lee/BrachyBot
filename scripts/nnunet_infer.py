import sys
if "-m" in sys.argv:
    from nnunetv2.inference.predict_from_raw_data import predict_entry_point_modelfolder
    predict_entry_point_modelfolder()
else:
    from nnunetv2.inference.predict_from_raw_data import predict_entry_point
    predict_entry_point()
