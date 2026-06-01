"""Grader metric dimensions (see grader_v0.md).

Each dimension is a pure function returning a similarity in [0, 1]:

    perceptual.perceptual_score(ref_rgb, cand_rgb)          # embeddings + SSIM
    color.color_score(ref_rgb, cand_rgb)                    # palette histogram
    structure.structure_score(ref_boxes, cand_boxes)        # rendered DOM boxes
    llem.llem_scores(ref_png, cand_png, dims)               # Design2Code LLEM: block_match/text/position/text_color
    vlm.vlm_score(ref_png_path, cand_png_path)               # constrained rubric judge

Submodules are NOT imported here — each pulls heavy deps (torch / skimage / litellm)
lazily, so callers import only the dimensions they need.
"""
