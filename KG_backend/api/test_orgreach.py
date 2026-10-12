"""Team/analytics reach follows the org-graph canvas, not the legacy chain.

Regression cover for the drift where /team and /api/team/analytics/ scoped to
``PortalUser.reports_to`` — a field the canvas editor never wrote — so a manager
owning a whole branch on the chart saw an empty team page.
"""
from django.test import TestCase

from .access import manageable_user_ids, manager_can_target
from .models import Company, OrgGraph, OrgNode, PortalUser
from . import orggraph as og


class OrgGraphReachTests(TestCase):
    """Canvas shape:

        root (boss)
        └── head            <- can_manage_team
            ├── (empty seat)
            │   └── deep        <- occupied seat under an empty one
            └── worker
        └── outsider        <- sibling branch under root, not under head
    """

    def setUp(self):
        self.company = Company.objects.create(name='ReachCo', active=True)
        self.graph = OrgGraph.objects.create(company=self.company)

        def mkuser(name, **kw):
            return PortalUser.objects.create(
                company=self.company, username=name, password_hash='x',
                role=kw.pop('role', 'after_sales_specialist'), active=True, **kw)

        self.boss = mkuser('boss', role='after_sales_manager', can_manage_team=True)
        self.head = mkuser('head', can_manage_team=True)
        self.deep = mkuser('deep')
        self.worker = mkuser('worker')
        self.outsider = mkuser('outsider')

        def mknode(occupant, parent=None, is_root=False):
            return OrgNode.objects.create(graph=self.graph, parent=parent,
                                          is_root=is_root, occupant=occupant)

        self.n_root = mknode(self.boss, is_root=True)
        self.n_head = mknode(self.head, self.n_root)
        self.n_empty = mknode(None, self.n_head)
        self.n_deep = mknode(self.deep, self.n_empty)
        self.n_worker = mknode(self.worker, self.n_head)
        self.n_outsider = mknode(self.outsider, self.n_root)

    # -- reach ------------------------------------------------------------

    def test_root_sees_whole_company(self):
        ids = manageable_user_ids(self.boss)
        self.assertEqual(
            ids, {self.head.id, self.deep.id, self.worker.id, self.outsider.id})

    def test_mid_tree_manager_sees_its_branch_only(self):
        """The regression: head owns a branch and must see all of it."""
        ids = manageable_user_ids(self.head)
        self.assertEqual(ids, {self.worker.id, self.deep.id})
        self.assertNotIn(self.outsider.id, ids)
        self.assertNotIn(self.boss.id, ids)

    def test_empty_seat_does_not_hide_the_branch_below_it(self):
        self.assertIn(self.deep.id, manageable_user_ids(self.head))

    def test_leaf_sees_nobody(self):
        self.assertEqual(manageable_user_ids(self.worker), set())

    def test_include_self(self):
        self.assertEqual(manageable_user_ids(self.worker, include_self=True),
                         {self.worker.id})

    def test_reach_is_unaffected_by_stale_reports_to(self):
        """A wrong legacy pointer must not widen or narrow canvas-derived reach."""
        PortalUser.objects.filter(id=self.outsider.id).update(reports_to=self.head)
        self.assertNotIn(self.outsider.id, manageable_user_ids(self.head))

    def test_seatless_user_falls_back_to_legacy_chain(self):
        loner = PortalUser.objects.create(
            company=self.company, username='loner', password_hash='x',
            role='after_sales_manager', can_manage_team=True, active=True)
        report = PortalUser.objects.create(
            company=self.company, username='report', password_hash='x',
            role='after_sales_specialist', active=True, reports_to=loner)
        self.assertIsNone(og.graph_subtree_user_ids(loner))
        self.assertIn(report.id, manageable_user_ids(loner))

    # -- authorization ----------------------------------------------------

    def test_manager_can_target_below_regardless_of_legacy_rank(self):
        """head and worker are both 'specialist' rank; the canvas decides."""
        self.assertTrue(manager_can_target(self.head, self.worker))
        self.assertTrue(manager_can_target(self.head, self.deep))

    def test_cannot_target_upward_or_sideways(self):
        self.assertFalse(manager_can_target(self.head, self.boss))
        self.assertFalse(manager_can_target(self.head, self.outsider))
        self.assertFalse(manager_can_target(self.head, self.head))

    def test_cannot_target_without_capability(self):
        self.assertFalse(manager_can_target(self.worker, self.deep))

    def test_cross_company_is_never_targetable(self):
        other = Company.objects.create(name='OtherCo', active=True)
        stranger = PortalUser.objects.create(
            company=other, username='stranger', password_hash='x',
            role='after_sales_specialist', active=True)
        self.assertFalse(manager_can_target(self.boss, stranger))
        self.assertNotIn(stranger.id, manageable_user_ids(self.boss))

    # -- legacy mirror ----------------------------------------------------

    def test_sync_reports_to_mirrors_the_canvas(self):
        og.sync_reports_to_from_graph(self.company)
        for u in (self.boss, self.head, self.deep, self.worker, self.outsider):
            u.refresh_from_db()
        self.assertIsNone(self.boss.reports_to_id)
        self.assertEqual(self.head.reports_to_id, self.boss.id)
        self.assertEqual(self.worker.reports_to_id, self.head.id)
        # Empty seat is skipped: deep reports to head, not to nobody.
        self.assertEqual(self.deep.reports_to_id, self.head.id)
        self.assertEqual(self.outsider.reports_to_id, self.boss.id)

    def test_sync_is_idempotent(self):
        og.sync_reports_to_from_graph(self.company)
        self.assertEqual(og.sync_reports_to_from_graph(self.company), 0)

    def test_sync_follows_a_reparent(self):
        self.n_worker.parent = self.n_outsider
        self.n_worker.save(update_fields=['parent'])
        og.sync_reports_to_from_graph(self.company)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.reports_to_id, self.outsider.id)
        self.assertNotIn(self.worker.id, manageable_user_ids(self.head))
