"""
CHI-NLP Pipeline — Main Orchestrator

Runs the full pipeline: corpus loading → chunking → embedding → 
semantic retrieval → LLM classification → aggregation → export.

Usage:
    python src/main.py                          # full pipeline
    python src/main.py --stage corpus           # corpus download only
    python src/main.py --stage embed            # embedding only (assumes corpus exists)
    python src/main.py --stage score            # scoring only (assumes embeddings exist)
    python src/main.py --stage export           # export only (assumes scores exist)
    python src/main.py --tradition buddhism     # run for one tradition only
    python src/main.py --axis indifference      # run for one axis only
    python src/main.py --dry-run                # show what would be done without API calls
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.corpus.loader import CorpusLoader
from src.preprocessing.chunker import TextChunker
from src.preprocessing.embedder import CorpusEmbedder
from src.scoring.retriever import SemanticRetriever
from src.scoring.classifier import PassageClassifier
from src.scoring.aggregator import ScoreAggregator
from src.export.json_exporter import JSONExporter
from src.export.evidence_exporter import EvidenceExporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("chi-pipeline")


def load_config():
    """Load pipeline config from YAML, then inject model from api_keys_seckin/config.py."""
    import yaml
    config_path = PROJECT_ROOT / "config" / "pipeline_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    api_config_dir = str(Path(
        r"C:\Users\secki\OneDrive\Desktop\claude_code_standalone_exercises\api_keys_seckin"
    ))
    if api_config_dir not in sys.path:
        sys.path.insert(0, api_config_dir)
    from config import MODEL  # noqa: PLC0415
    config["classification_model"] = MODEL

    return config


def run_corpus_stage(config, traditions=None):
    """Stage 1: Download and parse sacred text corpora."""
    logger.info("=== STAGE 1: Corpus Acquisition ===")
    loader = CorpusLoader(config, PROJECT_ROOT / "data" / "raw")
    
    corpora = config["corpora"]
    if traditions:
        corpora = [c for c in corpora if c["tradition"] in traditions]
    
    for corpus_def in corpora:
        logger.info(f"Loading: {corpus_def['id']} ({corpus_def['tradition']})")
        for text_def in corpus_def["texts"]:
            loader.load_text(corpus_def["id"], corpus_def["tradition"], text_def)
    
    stats = loader.get_stats()
    logger.info(f"Corpus loaded: {stats['total_texts']} texts, {stats['total_chars']} characters")
    return loader


def run_embed_stage(config, traditions=None):
    """Stage 2: Chunk texts and generate embeddings."""
    logger.info("=== STAGE 2: Preprocessing & Embedding ===")
    
    chunker = TextChunker(config["chunk_strategy"])
    embedder = CorpusEmbedder(
        model_name=config["embedding_model"],
        output_dir=PROJECT_ROOT / "data" / "embeddings"
    )
    
    raw_dir = PROJECT_ROOT / "data" / "raw"
    chunks = []
    
    for tradition_dir in sorted(raw_dir.iterdir()):
        if not tradition_dir.is_dir():
            continue
        if traditions and tradition_dir.name not in traditions:
            continue
            
        for text_file in sorted(tradition_dir.glob("*.json")):
            logger.info(f"Chunking: {text_file.name}")
            text_data = json.loads(text_file.read_text(encoding="utf-8"))
            text_chunks = chunker.chunk(text_data)
            chunks.extend(text_chunks)

    logger.info(f"Total chunks: {len(chunks)}")

    # Generate embeddings
    embedder.embed_chunks(chunks)

    # Save processed chunks
    processed_dir = PROJECT_ROOT / "data" / "processed"
    processed_dir.mkdir(exist_ok=True)
    (processed_dir / "chunks.json").write_text(
        json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    
    logger.info(f"Embeddings generated and indexed")
    return chunks


def run_score_stage(config, traditions=None, axes=None, dry_run=False):
    """Stage 3: Semantic retrieval + LLM classification + aggregation."""
    logger.info("=== STAGE 3: Axis Scoring ===")
    
    retriever = SemanticRetriever(
        embeddings_dir=PROJECT_ROOT / "data" / "embeddings",
        model_name=config["embedding_model"],
        top_k=config["top_k_retrieval"]
    )
    
    classifier = PassageClassifier(
        model=config["classification_model"],
        max_tokens=config["max_tokens_per_classification"],
        dry_run=dry_run
    )
    
    aggregator = ScoreAggregator(
        min_relevance=config["min_relevance_threshold"]
    )
    
    # Load axis definitions
    axis_defs = config["axes"]
    if axes:
        axis_defs = [a for a in axis_defs if a["id"] in axes]
    
    # Get unique traditions from processed chunks
    chunks_path = PROJECT_ROOT / "data" / "processed" / "chunks.json"
    all_chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    tradition_ids = sorted(set(c["tradition"] for c in all_chunks))
    if traditions:
        tradition_ids = [t for t in tradition_ids if t in traditions]
    
    # Load existing results so per-tradition runs merge rather than overwrite
    results_path = PROJECT_ROOT / "data" / "processed" / "scoring_results.json"
    if results_path.exists() and traditions:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    else:
        results = {}  # tradition -> axis -> {score, evidence[]}

    for tradition in tradition_ids:
        logger.info(f"\n--- Scoring: {tradition} ---")
        results[tradition] = {}
        
        for axis_def in axis_defs:
            axis_id = axis_def["id"]
            logger.info(f"  Axis: {axis_id}")
            
            # Retrieve relevant passages
            retrieved = retriever.retrieve(
                tradition=tradition,
                probes_high=axis_def["probes_high"],
                probes_low=axis_def.get("probes_low", [])
            )
            
            logger.info(f"    Retrieved {len(retrieved)} passages")
            
            if dry_run:
                logger.info(f"    [DRY RUN] Would classify {len(retrieved)} passages")
                results[tradition][axis_id] = {
                    "score": None,
                    "n_passages": len(retrieved),
                    "evidence": [{"passage": p["text"][:100], "source": p["source"]} for p in retrieved[:3]]
                }
                continue
            
            # Classify each passage
            classifications = []
            for passage in retrieved:
                result = classifier.classify(
                    passage=passage,
                    axis_def=axis_def,
                    tradition=tradition
                )
                if result:
                    classifications.append({**result, **passage})
            
            # Aggregate into axis score
            axis_result = aggregator.aggregate(classifications, axis_id)
            results[tradition][axis_id] = axis_result
            
            logger.info(f"    Score: {axis_result['score']:.1f} "
                        f"(n={axis_result['n_passages']}, "
                        f"CI=[{axis_result['ci_low']:.1f}, {axis_result['ci_high']:.1f}])")
    
    # Save raw results
    results_dir = PROJECT_ROOT / "data" / "processed"
    results_dir.mkdir(exist_ok=True)
    (results_dir / "scoring_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return results


def run_export_stage(config):
    """Stage 4: Export to JSON dataset + evidence document."""
    logger.info("=== STAGE 4: Export ===")

    results_path = PROJECT_ROOT / "data" / "processed" / "scoring_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    
    # JSON export with citation keys
    json_exporter = JSONExporter(config)
    json_exporter.export(results, output_dir / "chi_dataset_grounded.json")
    
    # Evidence document with full passages
    evidence_exporter = EvidenceExporter()
    evidence_exporter.export(results, output_dir / "evidence_document.md")
    
    logger.info(f"Exports written to {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="CHI-NLP Pipeline")
    parser.add_argument("--stage", choices=["corpus", "embed", "score", "export", "all"], default="all")
    parser.add_argument("--tradition", type=str, default=None, help="Run for one tradition only")
    parser.add_argument("--axis", type=str, default=None, help="Run for one axis only")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without API calls")
    args = parser.parse_args()
    
    config = load_config()
    traditions = [args.tradition] if args.tradition else None
    axes = [args.axis] if args.axis else None
    
    if args.stage in ("corpus", "all"):
        run_corpus_stage(config, traditions)
    
    if args.stage in ("embed", "all"):
        run_embed_stage(config, traditions)
    
    if args.stage in ("score", "all"):
        run_score_stage(config, traditions, axes, args.dry_run)
    
    if args.stage in ("export", "all"):
        run_export_stage(config)
    
    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()
