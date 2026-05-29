import torch
import torchvision.models as models
import torch.nn as nn

# 1. Modell-Struktur aufbauen
model = models.efficientnet_b0()
num_features = model.classifier[1].in_features
model.classifier[1] = nn.Linear(num_features, 8)

# 2. Checkpoint laden
weights_path = r"C:\Users\Kowalenko\PycharmProjects\AeroTandemStudio\models\handcam_base.pth"
checkpoint = torch.load(weights_path, map_location="cpu")
model.load_state_dict(checkpoint["model_state_dict"])
model.eval()

# 3. ONNX Export mit modernem Opset 18 & ohne alte dynamic_axes Warnung
onnx_path = r"C:\Users\Kowalenko\PycharmProjects\AeroTandemStudio\models\classifier_handcam.onnx"
dummy_input = torch.randn(1, 3, 224, 224)

print("Exportiere Modell nach ONNX (Opset 18)...")
torch.onnx.export(
    model,
    dummy_input,
    onnx_path,
    export_params=True,
    opset_version=18,  # Direkt auf die native Version von PyTorch setzen
    input_names=['input'],
    output_names=['output']
)
print(f"Erfolgreich und sauber konvertiert! Datei liegt unter: {onnx_path}")