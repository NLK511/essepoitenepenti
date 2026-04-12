"""
Concurrency stress tests for worker job claiming logic.

Design principles:
  - Simulate multiple workers (threads) competing for the same queue.
  - Verify that each job is claimed exactly once.
  - Verify atomicity of the claim_queued_run status transition.
"""

from __future__ import annotations

import unittest
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from trade_proposer_app.domain.enums import RunStatus
from trade_proposer_app.persistence.models import Base, JobRecord, RunRecord
from trade_proposer_app.repositories.runs import RunRepository


class WorkerConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        import os
        self.db_path = "concurrency_test.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
            
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"timeout": 30},
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        
        # Seed 50 queued jobs
        session = self.Session()
        job = JobRecord(name="test_job", job_type="proposal_generation", tickers_csv="AAPL")
        session.add(job)
        session.commit()
        
        for i in range(50):
            run = RunRecord(
                job_id=job.id,
                job_type="proposal_generation",
                status=RunStatus.QUEUED.value
            )
            session.add(run)
        session.commit()
        session.close()

    def tearDown(self) -> None:
        import os
        self.engine.dispose()
        if hasattr(self, "db_path") and os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_multiple_workers_never_claim_same_job(self) -> None:
        """
        Stress test: 10 threads competing for 50 jobs.
        """
        def worker_task(worker_name: str):
            claimed_ids = []
            # Each worker attempts to claim as many as possible
            session = self.Session()
            repo = RunRepository(session)
            while True:
                run = repo.claim_next_queued_run(worker_id=worker_name)
                if run is None:
                    break
                claimed_ids.append(run.id)
            session.close()
            return claimed_ids

        num_workers = 10
        all_claimed_ids = []
        
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_task, f"worker-{i}") for i in range(num_workers)]
            for future in as_completed(futures):
                all_claimed_ids.extend(future.result())

        # Verify exactly 50 claims
        self.assertEqual(len(all_claimed_ids), 50)
        
        # Verify uniqueness
        unique_ids = set(all_claimed_ids)
        self.assertEqual(len(unique_ids), 50, "Duplicate claims detected!")

    def test_atomic_claim_transition_integrity(self) -> None:
        """
        Verify that even under contention, the DB state reflects 
        exactly 1 worker per job and all jobs are RUNNING.
        """
        def worker_task(worker_name: str):
            session = self.Session()
            repo = RunRepository(session)
            # Try to claim exactly 1 job
            repo.claim_next_queued_run(worker_id=worker_name)
            session.close()

        num_workers = 50 # 1 worker per job
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_task, f"worker-{i}") for i in range(num_workers)]
            for future in as_completed(futures):
                future.result()

        # Check final DB state
        session = self.Session()
        runs = session.query(RunRecord).all()
        
        for run in runs:
            self.assertEqual(run.status, RunStatus.RUNNING.value)
            self.assertIsNotNone(run.worker_id)
            self.assertIn("worker-", run.worker_id)
            
        # Verify worker distribution (should be balanced if claim_next is fair)
        worker_ids = [run.worker_id for run in runs]
        self.assertEqual(len(set(worker_ids)), 50)
        
        session.close()

if __name__ == "__main__":
    unittest.main()
