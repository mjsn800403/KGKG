"""The support chat stays clear of the paid AI assistant: no shared routes, and
no AI/LLM/RAG dependency anywhere in the support or notification code."""
import ast
import pathlib

from django.test import SimpleTestCase
from django.urls import get_resolver, reverse
from django.urls.resolvers import URLPattern, URLResolver

import api.notifications
import api.support_chat

FORBIDDEN_MODULES = {
    'anthropic', 'openai', 'google', 'cohere', 'mistralai', 'ollama', 'langchain', 'llama_index',
    'torch', 'transformers', 'sentence_transformers', 'sqlite_vec', 'numpy', 'requests', 'httpx',
}
FORBIDDEN_PROJECT_PREFIXES = ('api.rag', 'api.assist_lookup', 'api.chatlog', 'api.behavior',
                              'api.evalsuite', 'api.recommend')


def _routes(patterns=None, prefix=''):
    out = []
    for p in patterns if patterns is not None else get_resolver('api.urls').url_patterns:
        route = str(p.pattern)
        if isinstance(p, URLResolver):
            out += _routes(p.url_patterns, prefix + route)
        elif isinstance(p, URLPattern):
            out.append(prefix + route)
    return out


def _sources(package):
    root = pathlib.Path(package.__file__).parent
    return [f for f in root.glob('*.py') if not f.name.startswith('test')
            and f.name != 'helpers.py']


def _imports(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom):
            base = ('.' * node.level) + (node.module or '')
            yield base


class RouteSeparationTests(SimpleTestCase):
    def test_no_django_route_uses_the_assistants_api_chat_prefix(self):
        offenders = [r for r in _routes() if r.startswith(('api/chat', 'api/admin/chat/'))]
        self.assertEqual(offenders, [])

    def test_every_support_chat_route_is_namespaced(self):
        mine = [r for r in _routes() if 'support-chat' in r]
        self.assertGreaterEqual(len(mine), 12)
        for r in mine:
            self.assertTrue(r.startswith(('api/support-chat/', 'api/admin/support-chat/')), r)

    def test_existing_assistant_chat_routes_still_resolve(self):
        self.assertEqual(reverse('chat_log_record'), '/api/auth/chat-log/')
        self.assertEqual(reverse('chat_feedback'), '/api/auth/chat-feedback/')
        self.assertEqual(reverse('team_chat_logs'), '/api/team/chat-logs/')
        self.assertEqual(reverse('admin_chat_logs'), '/api/admin/chat-logs/')

    def test_the_assistants_related_names_are_unchanged(self):
        from api.models import ChatLog
        self.assertEqual(ChatLog._meta.get_field('user').remote_field.related_name, 'chat_logs')
        self.assertEqual(ChatLog._meta.get_field('company').remote_field.related_name, 'chat_logs')


class NoAiDependencyTests(SimpleTestCase):
    def test_support_and_notification_code_import_no_ai_stack(self):
        offences = []
        for pkg in (api.support_chat, api.notifications):
            for f in _sources(pkg):
                for name in _imports(f):
                    top = name.lstrip('.').split('.')[0]
                    if top in FORBIDDEN_MODULES:
                        offences.append((f.name, name))
                    dotted = name.lstrip('.')
                    if name.startswith('..') and dotted.split('.')[0] in {
                            p.split('.')[1] for p in FORBIDDEN_PROJECT_PREFIXES}:
                        offences.append((f.name, name))
                    if name.startswith('api.') and name.startswith(FORBIDDEN_PROJECT_PREFIXES):
                        offences.append((f.name, name))
        self.assertEqual(offences, [])

    def test_the_support_code_has_no_llm_or_rag_vocabulary_in_its_calls(self):
        words = ('openai', 'anthropic', 'completion', 'embedding', 'metis', 'prompt', 'vector')
        hits = []
        for pkg in (api.support_chat, api.notifications):
            for f in _sources(pkg):
                code = f.read_text(encoding='utf-8').lower()
                hits += [(f.name, w) for w in words if w in code]
        self.assertEqual(hits, [])
