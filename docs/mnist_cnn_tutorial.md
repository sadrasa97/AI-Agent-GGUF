# CNN for MNIST - Complete Tutorial

## Introduction
This tutorial demonstrates how to build, train, and evaluate a Convolutional Neural Network (CNN) for classifying handwritten digits from the MNIST dataset using PyTorch.

## Setup
```python
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt
```

## Data Preparation
```python
# Transformations for the training data
transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.1307,), (0.3081,))  # MNIST mean and std
])

# Load MNIST dataset
train_dataset = datasets.MNIST(root='./data', train=True, download=True, transform=transform)
test_dataset = datasets.MNIST(root='./data', train=False, download=True, transform=transform)

# Data loaders
train_loader = DataLoader(dataset=train_dataset, batch_size=64, shuffle=True)
test_loader = DataLoader(dataset=test_dataset, batch_size=1000, shuffle=False)
```

## CNN Architecture
```python
class MNIST_CNN(nn.Module):
    def __init__(self):
        super(MNIST_CNN, self).__init__()
        # First convolutional layer
        self.conv1 = nn.Conv2d(in_channels=1, out_channels=32, kernel_size=3, stride=1)
        self.conv2 = nn.Conv2d(32, 64, 3, 1)

        # After conv/pool operations:
        # 28x28 -> conv3x3 -> 26x26 -> pool2x2 -> 13x13
        # 13x13 -> conv3x3 -> 11x11 -> pool2x2 -> 5x5
        # Flatten size = 64 * 5 * 5 = 1600
        self.fc1 = nn.Linear(1600, 128)
        self.fc2 = nn.Linear(128, 10)  # 10 classes (digits 0-9)

    def forward(self, x):
        # Conv layers with ReLU activation and max pooling
        x = F.relu(self.conv1(x))
        x = F.max_pool2d(x, 2)
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2)

        # Flatten for fully connected layers
        x = x.view(x.size(0), -1)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return x
```

## Training the Model
```python
def train(model, device, train_loader, optimizer, criterion, epoch):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(device), target.to(device)

        optimizer.zero_grad()
        output = model(data)
        loss = criterion(output, target)
        loss.backward()
        optimizer.step()

        if batch_idx % 100 == 0:
            print(
                f'Train Epoch: {epoch} [{batch_idx * len(data)}/{len(train_loader.dataset)}] '
                f'Loss: {loss.item():.4f}'
            )


def test(model, device, test_loader, criterion):
    model.eval()
    test_loss = 0.0
    correct = 0
    with torch.no_grad():
        for data, target in test_loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            test_loss += criterion(output, target).item() * data.size(0)
            pred = output.argmax(dim=1, keepdim=True)
            correct += pred.eq(target.view_as(pred)).sum().item()

    test_loss /= len(test_loader.dataset)
    accuracy = 100.0 * correct / len(test_loader.dataset)
    print(
        f'Test set: Average loss: {test_loss:.4f}, '
        f'Accuracy: {correct}/{len(test_loader.dataset)} ({accuracy:.2f}%)'
    )
    return test_loss, accuracy
```

## Main Execution
```python
def main():
    # Device configuration
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")

    # Initialize model, loss function, and optimizer
    model = MNIST_CNN().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    # Training loop
    epochs = 10
    best_acc = 0.0
    for epoch in range(1, epochs + 1):
        train(model, device, train_loader, optimizer, criterion, epoch)
        _, accuracy = test(model, device, test_loader, criterion)

        # Save best model based on accuracy
        if accuracy > best_acc:
            best_acc = accuracy
            torch.save(model.state_dict(), 'best_mnist_cnn.pth')
            print(f"Saved new best model with accuracy: {accuracy:.2f}%")


if __name__ == '__main__':
    main()
```

## Visualizing Results
```python
def plot_digit(image, label, prediction=None):
    """Plot a single digit image with its label and prediction."""
    image = image.squeeze(0).numpy()
    plt.imshow(image, cmap='gray')
    title = f'Label: {label}'
    if prediction is not None:
        title += f'\nPred: {prediction}'
    plt.title(title)
    plt.axis('off')


# Example usage (after model training)
data, target = train_dataset[0]
model.eval()
with torch.no_grad():
    output = model(data.unsqueeze(0).to(device))
    pred = output.argmax(dim=1).item()

plot_digit(data, target.item(), pred)
plt.show()
```

## Tips for Improvement
1. **Data Augmentation**: Add random rotations and translations to improve generalization.
2. **Batch Normalization**: Add `nn.BatchNorm2d()` layers after convolutional layers.
3. **Learning Rate Scheduling**: Use `torch.optim.lr_scheduler.StepLR` to adjust the learning rate.
4. **Regularization**: Add dropout layers to prevent overfitting.
5. **Advanced Architectures**: Try ResNet-like architectures for better performance.

## Expected Results
With this basic CNN, you should achieve:
- Training accuracy: around 99.5% after 10 epochs.
- Test accuracy: around 99.0% to 99.2% (may vary slightly).
- Training time: around 10 to 15 minutes on CPU, much faster on GPU.

This tutorial provides a solid foundation for understanding CNNs and can be extended to more complex computer vision tasks.
