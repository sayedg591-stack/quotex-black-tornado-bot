        # Support martingale result labels (MTG_WIN / MTG_LOSS) and normal results
        if outcome == "WIN":
            res_str = "✅ WIN"
        elif outcome == "MTG_WIN":
            res_str = "🏆 MTG WIN"
        elif outcome == "LOSS" or outcome == "MTG_LOSS":
            # Treat MTG_LOSS same as LOSS (customize if you want a special label)
            res_str = "❌ LOSS"
        elif outcome == "DRAW":
            res_str = "⚖️ DRAW"
        else:
            res_str = "⚠️ UNVERIFIED"
