import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from audio_generation_claim_audit.audit import audit, claims, evidence, main, remove_matches
from audio_generation_claim_audit.phrases import AUDIOGENERATION, NOAUDIOGENERATION

FIXTURES = Path(__file__).parent / 'fixtures'


class Claims(unittest.TestCase):
    def test_fences(self):
        for fence in ('```', '~~~', '   ````'):
            self.assertEqual(claims(fence + '\naudio generation\n' + fence.strip()), (False, False))
    def test_inline(self):
        self.assertEqual(claims('`audio generation`'), (True, False))
    def test_negative(self):
        for phrase in NOAUDIOGENERATION:
            self.assertEqual(claims(phrase), (False, True), phrase)
    def test_positive(self):
        for phrase in AUDIOGENERATION:
            self.assertEqual(claims(phrase), (True, False), phrase)
    def test_hyphens(self):
        self.assertEqual(claims('text-to-audio'), (True, False))
    def test_contraction(self):
        self.assertEqual(claims("doesn't support audio generation"), (False, True))
    def test_paragraphs(self):
        self.assertEqual(claims('supports audio\ngeneration'), (True, False))
        self.assertEqual(claims('supports audio\n\ngeneration'), (False, False))
    def test_longest(self):
        self.assertEqual(remove_matches('generates audio from text prompts', ('generates audio', 'generates audio from text prompts')), (' ', True))
    def test_sorted(self):
        for phrases in (AUDIOGENERATION, NOAUDIOGENERATION):
            self.assertEqual(list(phrases), sorted(set(phrases), key=lambda p: (-len(p), p)))
    def test_boundaries(self):
        self.assertEqual(claims('regenerates musically'), (False, False))


class Evidence(unittest.TestCase):
    pass

POSITIVES = [
 'import diffusers\ndiffusers.AudioLDM2Pipeline()',
 'import diffusers as d\nd.AudioLDM2Pipeline()',
 'from diffusers import AudioLDM2Pipeline as P\nP()',
 'import diffusers\ndiffusers.AudioLDMPipeline.from_pretrained("x")',
 'from diffusers import AudioLDMPipeline as P\nP.from_pretrained("x")',
 'from diffusers import StableAudioPipeline\nStableAudioPipeline()',
 'from transformers import MusicgenForConditionalGeneration\nMusicgenForConditionalGeneration()',
 'from transformers import MusicgenForConditionalGeneration as M\nM()',
 'from audiocraft.models import MusicGen\nMusicGen.get_pretrained("x")',
 'from transformers import pipeline\npipeline("text-to-audio")',
 'import transformers as t\nt.pipeline(task="audio-generation")',
 'client.music.generate(prompt="x")',
 'from diffusers import StableAudioPipeline as P\nP.from_single_file("x")',
 'from transformers import MusicgenModel\nMusicgenModel()',
]
NEGATIVES = [
 'from diffusers import AudioLDM2Pipeline',
 'import pyttsx3\npyttsx3.init().say("hi")',
 'from gtts import gTTS\ngTTS("hi")',
 'import whisper\nwhisper.load_model("x").transcribe("x")',
 'import playsound\nplaysound.playsound("x")',
 'import pygame\npygame.mixer.music.play()',
 'import sounddevice as sd\nsd.play([])',
 'import sounddevice as sd\nsd.rec(100)',
 'import sounddevice as sd\nsd.InputStream().read(10)',
 'import soundfile\nsoundfile.write("x", [], 1)',
 'import librosa\nlibrosa.load("x")',
 'from transformers import pipeline\npipeline("audio-classification")',
 'from transformers import pipeline\npipeline("text-to-speech")',
 'from diffusers import StableDiffusionPipeline\nStableDiffusionPipeline()',
 'from diffusers import CogVideoXPipeline\nCogVideoXPipeline()',
 'from diffusers import AudioLDM2Pipeline\ndef AudioLDM2Pipeline(): pass\nAudioLDM2Pipeline()',
 'from diffusers import AudioLDM2Pipeline\nclass AudioLDM2Pipeline: pass\nAudioLDM2Pipeline()',
 's = "audio generation"',
 'import subprocess\nsubprocess.run(["audio-generation"])',
 'invalid python !!!',
 'AudioLDM2Pipeline()',
]
for i, source in enumerate(POSITIVES):
    def test(self, source=source): self.assertTrue(evidence(source), source)
    setattr(Evidence, 'test_positive_%02d' % i, test)
for i, source in enumerate(NEGATIVES):
    def test(self, source=source): self.assertFalse(evidence(source), source)
    setattr(Evidence, 'test_negative_%02d' % i, test)


class Integration(unittest.TestCase):
    def invoke(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try: code = main(list(args))
            except SystemExit as error: code = error.code
        return code, out.getvalue()
    def test_good(self):
        self.assertEqual(audit(FIXTURES/'good')['verdict'], 'PASS')
    def test_bad(self):
        code, output = self.invoke(str(FIXTURES/'bad'), '--json')
        result=json.loads(output)
        self.assertEqual(code, 2)
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(result['findings'][0]['severity'], 'HIGH')
        self.assertEqual(result['findings'][0]['rule'], 'documented-audio-generation-claim-false')
        self.assertEqual(set(result), {'verdict', 'findings', 'files_scanned'})
    def test_testonly(self):
        code, output=self.invoke(str(FIXTURES/'testonly'), '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['findings'][0]['severity'], 'MEDIUM')
        self.assertEqual(self.invoke(str(FIXTURES/'testonly'), '--fail-on', 'MEDIUM')[0], 2)
    def test_negative(self):
        code, output=self.invoke(str(FIXTURES/'no-audio-generation'), '--json')
        findings=json.loads(output)['findings']
        self.assertEqual(code, 2)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['severity'], 'HIGH')
        self.assertEqual(findings[0]['rule'], 'documented-no-audio-generation-claim-false')
    def test_noclaim(self):
        self.assertEqual(audit(FIXTURES/'noclaim')['verdict'], 'PASS')
    def test_ignore(self):
        self.assertEqual(audit(FIXTURES/'bad', ['README.*'])['verdict'], 'PASS')
    def test_verbose(self):
        self.assertIn('Files scanned: 2', self.invoke(str(FIXTURES/'good'), '--verbose')[1])
    def test_version(self):
        self.assertEqual(self.invoke('--version'), (0, '0.1.0\n'))
    def test_invalid(self):
        self.assertEqual(self.invoke('/nonexistent/audit-root')[0], 1)
    def test_usage(self):
        self.assertEqual(self.invoke('--unknown')[0], 1)
    def test_excluded_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'README.md').write_text('audio generation')
            for sub in ('docs', 'examples', 'fixtures'):
                (root/sub).mkdir()
                (root/sub/'app.py').write_text(POSITIVES[0])
            (root/'link.py').symlink_to(root/'examples/app.py')
            self.assertEqual(audit(root)['findings'][0]['severity'], 'HIGH')
    def test_docs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'docs').mkdir()
            (root/'docs/a.md').write_text('audio generation')
            self.assertEqual(len(audit(root)['findings']), 1)


if __name__ == '__main__':
    unittest.main()
